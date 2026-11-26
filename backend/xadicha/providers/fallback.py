"""Asosiy provayder (Gemini) ishlamasa — zaxira provayderga (Ollama) avtomatik o'tish.

Har bir chaqiruv AYNAN bir xil system/user matn va ekran bilan zaxiraga beriladi — suhbat konteksti, vazifa
tarixi va qadamlar yo'qolmaydi. Qaysi provayder javob bergani `name`/`info()` orqali halol ko'rsatiladi:
Gemini ishlamagan paytda tizim "gemini ishlayapti" deb ko'rsatmaydi.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from ..redaction import redact
from ..vision.screen import Screenshot
from .base import LLMProvider, ProviderError

log = logging.getLogger("xadicha")

# Xato turi → asosiy provayder qancha vaqt chetlab o'tiladi (soniya). Har bir buyruq kutib qolmasin.
COOLDOWN_S = {"auth": 600.0, "config": 600.0, "quota": 60.0, "server": 30.0, "network": 20.0, "timeout": 20.0}
# Grounding'ga xos xatolar (masalan, bepul tarifda Google Search mavjud emas) — generatsiyani to'xtatmaydi
GROUNDING_COOLDOWN_S = 300.0


class FallbackProvider(LLMProvider):
    def __init__(self, primary: LLMProvider | None, secondary: LLMProvider, primary_name: str = "gemini",
                 primary_model: str = "", primary_error: str = "", clock: Callable[[], float] = time.monotonic):
        self.primary = primary
        self.secondary = secondary
        self.primary_name = primary.name if primary is not None else primary_name
        self.primary_model = getattr(primary, "model", "") or primary_model
        self._clock = clock
        self._lock = threading.Lock()
        self._down_until = float("inf") if primary is None else 0.0
        self._grounding_down_until = 0.0
        self.last_error = redact(primary_error)
        self.last_error_kind = "config" if primary is None else ""
        self.grounding_error = ""
        self.active = secondary.name if primary is None else self.primary_name
        self.fallback_count = 0

    # --- ko'rinish: oxirgi javob bergan provayder ---
    @property
    def name(self) -> str:   # type: ignore[override]
        return self.active

    @property
    def model(self) -> str:
        if self.active == self.primary_name:
            return getattr(self.primary, "model", "") or self.primary_model   # zanjirda oxirgi javob bergan Gemini modeli
        return getattr(self.secondary, "model", "")

    @property
    def supports_vision(self) -> bool:   # type: ignore[override]
        target = self.primary if self._primary_ready() else self.secondary
        return bool(getattr(target, "supports_vision", False))

    @property
    def supports_grounding(self) -> bool:
        return (self._primary_ready() and bool(getattr(self.primary, "supports_grounding", False))
                and self._clock() >= self._grounding_down_until)

    # --- holat ---
    offline = False   # oflayn rejim: faqat lokal zaxira (Ollama), bulutga so'rov yo'q

    def _primary_ready(self) -> bool:
        return not self.offline and self.primary is not None and self._clock() >= self._down_until

    def _mark_failed(self, err: ProviderError) -> None:
        kind = getattr(err, "kind", "error")
        with self._lock:
            self.last_error, self.last_error_kind = redact(str(err)), kind
            self._down_until = self._clock() + COOLDOWN_S.get(kind, 15.0)
            self.fallback_count += 1
        if hasattr(self.primary, "invalidate_health"):
            self.primary.invalidate_health()
        log.warning("%s ishlamadi (%s): %s — zaxira: %s", self.primary_name, kind, self.last_error, self.secondary.name)

    def _mark_ok(self) -> None:
        with self._lock:
            self.active = self.primary_name
            if self.last_error_kind != "":
                log.info("%s yana ishlayapti", self.primary_name)
            self.last_error, self.last_error_kind = "", ""

    # --- LLMProvider ---
    def complete(self, system: str, user: str, screen: Screenshot | None) -> str:
        primary_err: ProviderError | None = None
        if self._primary_ready():
            try:
                out = self.primary.complete(system, user, screen)
                self._mark_ok()
                return out
            except ProviderError as e:
                primary_err = e
                self._mark_failed(e)
        sec_screen = screen if getattr(self.secondary, "supports_vision", False) else None
        try:
            out = self.secondary.complete(system, user, sec_screen)
        except ProviderError as e2:
            reason = self.last_error or (str(primary_err) if primary_err else "")
            raise ProviderError(redact(f"{reason} Zaxira ({self.secondary.name}) ham ishlamadi: {e2}").strip(),
                                kind=getattr(e2, "kind", "error")) from e2
        self.active = self.secondary.name
        return out

    @property
    def supports_streaming(self) -> bool:
        return self._primary_ready() and bool(getattr(self.primary, "supports_streaming", False))

    def stream_text(self, system: str, user: str):
        """Faqat asosiy provayderda; birinchi bo'lakkacha xato bo'lsa — ProviderError (agent zaxira yo'liga o'tadi)."""
        if not self.supports_streaming:
            raise ProviderError("oqimli javob hozir mavjud emas", kind="unavailable")
        got = False
        try:
            for t in self.primary.stream_text(system, user):
                got = True
                yield t
        except ProviderError as e:
            if not got:
                self._mark_failed(e)
            raise
        self._mark_ok()

    def grounded_answer(self, *args: Any, **kwargs: Any) -> Any:
        """Faqat asosiy provayderda (Gemini). Mavjud bo'lmasa — ProviderError; agent oddiy qidiruvga o'tadi."""
        if not self.supports_grounding:
            raise ProviderError(self.grounding_error or self.last_error or "Google Search grounding hozir mavjud emas.",
                                kind="unavailable")
        try:
            out = self.primary.grounded_answer(*args, **kwargs)
        except ProviderError as e:
            kind = getattr(e, "kind", "error")
            self.grounding_error = redact(str(e))
            self._grounding_down_until = self._clock() + GROUNDING_COOLDOWN_S
            if kind in ("auth", "network", "timeout"):
                self._mark_failed(e)   # umumiy muammo (kalit/tarmoq) — generatsiya ham zaxiraga o'tadi
            else:
                log.warning("Google Search grounding ishlamadi (%s): %s", kind, self.grounding_error)
            raise
        self.grounding_error = ""
        self._mark_ok()
        return out

    def health(self) -> tuple[bool, str]:
        sec_ok, sec_detail = self.secondary.health()
        if self.primary is None:
            return sec_ok, f"{self.last_error} → {self.secondary.name}: {sec_detail}"
        ok, detail = self.primary.health()
        if ok and self._primary_ready():
            return True, "ok"
        reason = self.last_error if not self._primary_ready() and self.last_error else detail
        return sec_ok, f"{self.primary_name}: {reason} → zaxira {self.secondary.name}: {sec_detail}"

    def info(self) -> dict[str, Any]:
        """Status uchun xavfsiz ma'lumot (kalitsiz)."""
        p_ok, p_detail = self.primary.health() if self.primary is not None else (False, self.last_error)
        s_ok, s_detail = self.secondary.health()
        ready = self._primary_ready()
        if self.offline:
            p_ok, p_detail = False, "oflayn rejim — ishlatilmaydi"
        elif not ready and self.primary is not None:
            p_ok = False
            p_detail = self.last_error or p_detail
        return {
            "primary": {"name": self.primary_name, "model": self.primary_model, "ok": bool(p_ok), "detail": p_detail,
                        "models": list(getattr(self.primary, "models", [self.primary_model])),
                        "active_model": getattr(self.primary, "model", self.primary_model)},
            "fallback": {"name": self.secondary.name, "model": getattr(self.secondary, "model", ""), "ok": bool(s_ok),
                         "detail": s_detail},
            "active": self.active if ready or self.active == self.secondary.name else self.secondary.name,
            "using_fallback": not ready or self.active != self.primary_name,
            "last_error": self.last_error,
            "last_error_kind": self.last_error_kind,
            "retry_in_s": max(0, int(self._down_until - self._clock())) if self.primary is not None and not ready else 0,
            "fallback_count": self.fallback_count,
            "grounding": {"available": self.supports_grounding, "detail": self.grounding_error},
            "offline": self.offline,
        }

    def warmup(self) -> None:
        # Asosiy: ishlaydigan Gemini modelini oldindan aniqlash; zaxira — faqat asosiy ishlamasa xotiraga yuklanadi
        if self._primary_ready() and hasattr(self.primary, "warmup"):
            self.primary.warmup()
        if not self._primary_ready() or not getattr(self.primary, "_available_models", lambda: [1])():
            self.secondary.warmup()
