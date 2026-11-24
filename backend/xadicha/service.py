"""Ilova xizmati: agent, nutq, tasdiqlar va hodisalarni bir joyda boshqaradi (API va CLI uchun)."""

from __future__ import annotations

import logging
import uuid
import platform
import threading
import time
from collections.abc import Callable
from typing import Any

from .adapters import OSAdapter, make_adapter
from .agent import Agent
from .config import Config
from .models import Action, Mode, RiskLevel, TaskRecord
from .providers import LLMProvider, ProviderError, RuleBasedProvider, make_provider
from .speech.stt import Listener, Transcript
from .speech.tts import Speaker
from .storage import Storage


def _setup_logging(path) -> None:
    """Xatolar backend/data/xadicha.log fayliga yoziladi (tahlil uchun)."""
    logger = logging.getLogger("xadicha")
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        return
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


class PendingConfirmation:
    def __init__(self, task_id: str, action: Action, risk: RiskLevel, reason: str, timeout: float):
        self.id = uuid.uuid4().hex[:12]   # bir vazifada bir nechta tasdiq bo'lishi mumkin — har biri alohida
        self.task_id, self.action, self.risk, self.reason = task_id, action, risk, reason
        self.event = threading.Event()
        self.approved = False
        self.outcome = ""                  # "approved" | "denied" | "timeout" | "cancelled"
        self.expires_at = time.time() + timeout
        self._lock = threading.Lock()

    def resolve(self, outcome: str, approved: bool = False) -> bool:
        """Faqat birinchi javob qabul qilinadi (takroriy bosish yoki kech javob e'tiborsiz)."""
        with self._lock:
            if self.event.is_set():
                return False
            self.approved, self.outcome = approved, outcome
            self.event.set()
            return True

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "task_id": self.task_id, "action": self.action.model_dump(),
                "description": self.action.describe(), "risk": self.risk.value, "reason": self.reason,
                "expires_at": self.expires_at}


def mic_error_message(e: Exception) -> str:
    """sounddevice/PortAudio xatosini foydalanuvchi tushunadigan matnga aylantiradi."""
    raw = f"{e.__class__.__name__}: {e}"
    low = raw.lower()
    if "no default input" in low or "invalid device" in low or "device unavailable" in low or "-9996" in low:
        return "Mikrofon topilmadi. Mikrofon ulanganini va tizimda tanlanganini tekshiring."
    if "permission" in low or "not permitted" in low or "-9986" in low or "denied" in low:
        return ("Mikrofonga ruxsat yo'q. System Settings → Privacy & Security → Microphone bo'limida "
                "Terminal'ga (backend ishlayotgan ilovaga) ruxsat bering.")
    if "portaudio" in low or "sounddevice" in low:
        return f"Mikrofon xatosi (PortAudio): {e}"
    return f"Mikrofon: {raw}"


class XadichaService:
    def __init__(self, cfg: Config, provider: LLMProvider | None = None, adapter: OSAdapter | None = None,
                 storage: Storage | None = None, screen_fn=None, confirm_timeout: float = 120):
        self.cfg = cfg
        self.provider_error = ""
        if provider is None:
            try:
                provider = make_provider(cfg)
            except ProviderError as e:
                self.provider_error = str(e)
                provider = RuleBasedProvider()
        self.provider = provider
        self.adapter = adapter or make_adapter()
        self.storage = storage or Storage(cfg.db_path)
        self.storage.fail_stale_running()
        _setup_logging(cfg.db_path.parent / "xadicha.log")
        self.speaker = Speaker(cfg.tts_engine, cfg.tts_rate,
                               {"uz": cfg.voice_uz, "ru": cfg.voice_ru, "en": cfg.voice_en}, cfg.tts_enabled)
        self.listener = Listener(cfg.whisper_model, cfg.stt_engine)
        self.confirm_timeout = confirm_timeout
        self.listeners: list[Callable[[dict[str, Any]], None]] = []
        self.pending: PendingConfirmation | None = None
        self.current_task: str | None = None
        self._run_lock = threading.Lock()
        self.listening = "idle"            # "idle" | "recording" | "transcribing" — qayta ulanishda tiklash uchun
        self._listen_stop: threading.Event | None = None
        self._listen_thread: threading.Thread | None = None
        self._listen_result: Transcript | None = None
        self._listen_error = ""
        self._listen_cancelled = False

        if screen_fn is None and self.adapter.name in ("macos", "windows"):
            from .vision.screen import capture

            screen_fn = lambda: capture(self.adapter.screen_size(), cfg.screen_max_side)  # noqa: E731
        self.agent = Agent(cfg, self.provider, self.adapter, self.storage, confirm=self._confirm,
                           on_event=self.emit, screen_fn=screen_fn)

    def warmup(self) -> None:
        """Model va nutqni aniqlashni fonda oldindan yuklash — birinchi buyruq tezroq bo'ladi."""
        def work() -> None:
            self.provider.warmup()
            self.listener.warmup()
            self.emit({"type": "warm", "stt_engine": self.listener.engine})
        threading.Thread(target=work, daemon=True).start()

    # --- hodisalar ---
    def subscribe(self, fn: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self.listeners.append(fn)
        return lambda: self.listeners.remove(fn) if fn in self.listeners else None

    def emit(self, event: dict[str, Any]) -> None:
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:  # noqa: BLE001
                pass

    # --- tasdiq ---
    def _confirm(self, task: TaskRecord, action: Action, risk: RiskLevel, reason: str) -> bool | str:
        p = PendingConfirmation(task.id, action, risk, reason, self.confirm_timeout)
        self.pending = p
        self.emit({"type": "confirm_request", **p.public()})
        if not p.event.wait(self.confirm_timeout):
            p.resolve("timeout")
        self.pending = None
        self.emit({"type": "confirm_resolved", "id": p.id, "task_id": task.id,
                   "approved": p.approved, "outcome": p.outcome})
        if p.approved:
            return True
        return p.outcome if p.outcome in ("timeout", "cancelled") else False

    def answer_confirmation(self, task_id: str, approve: bool, confirmation_id: str | None = None) -> str:
        """"ok" — qabul qilindi; "none" — kutilayotgan tasdiq yo'q (muddati tugagan yoki boshqa vazifa);
        "already" — bu tasdiqqa allaqachon javob berilgan."""
        p = self.pending
        if p is None or p.task_id != task_id or (confirmation_id and confirmation_id != p.id):
            return "none"
        if not p.resolve("approved" if approve else "denied", approved=approve):
            return "already"
        return "ok"

    # --- vazifalar ---
    @property
    def busy(self) -> bool:
        return self._run_lock.locked() or self.current_task is not None

    def run_task(self, instruction: str, language: str = "uz", mode: Mode = Mode.multimodal,
                 speak: bool = True, _locked: bool = False) -> TaskRecord:
        if not _locked and not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Boshqa vazifa bajarilmoqda.")
        try:
            def track(e: dict[str, Any]) -> None:
                if e["type"] == "task_started":
                    self.current_task = e["task_id"]

            unsub = self.subscribe(track)
            try:
                task = self.agent.run(instruction, language, mode)
            finally:
                unsub()
            if speak and task.final_message:
                spoken = self.speaker.say(task.final_message, task.language)
                self.emit({"type": "spoken", "task_id": task.id, "text": task.final_message, "audio": spoken})
            return task
        finally:
            self.current_task = None
            self._run_lock.release()

    def start_task(self, instruction: str, language: str = "uz", mode: Mode = Mode.multimodal) -> None:
        # Qulf shu yerda olinadi: ikki tez so'rov ikkalasi ham "bo'sh" deb ko'rib, ikki vazifa boshlamasligi uchun
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Boshqa vazifa bajarilmoqda.")
        try:
            threading.Thread(target=self._safe_run, args=(instruction, language, mode), daemon=True).start()
        except Exception:
            self._run_lock.release()
            raise

    def _safe_run(self, instruction: str, language: str, mode: Mode) -> None:
        try:
            self.run_task(instruction, language, mode, _locked=True)
        except Exception as e:  # noqa: BLE001
            self.emit({"type": "error", "message": f"{e.__class__.__name__}: {e}"})

    def stop(self) -> None:
        """Favqulodda to'xtatish: joriy vazifa, kutilayotgan tasdiq, ovoz va mikrofon."""
        self.agent.stop()
        self.speaker.stop()
        p = self.pending
        if p:
            p.resolve("cancelled")
        self.cancel_listening()
        self.emit({"type": "stopped"})

    # --- tinglash ---
    def _set_listening(self, state: str, **extra: Any) -> None:
        self.listening = state
        self.emit({"type": "listening", "state": state, **extra})

    def start_listening(self, language: str | None = None) -> str:
        """Mikrofonni faqat backend (sounddevice) yozadi; interfeys ovoz darajasini `mic_level` hodisasidan oladi.
        Qaytaradi: joriy holat ("recording" yoki allaqachon ketayotgan holat)."""
        if self._listen_thread and self._listen_thread.is_alive():
            return self.listening
        self.speaker.stop()
        stop_ev = threading.Event()
        self._listen_stop = stop_ev
        self._listen_result = None
        self._listen_error = ""
        self._listen_cancelled = False
        last = [0.0]

        def on_level(level: float) -> None:
            now = time.monotonic()
            if now - last[0] >= 0.066:   # ~15 marta/soniya — WebSocket'ni to'ldirmaslik uchun
                last[0] = now
                self.emit({"type": "mic_level", "level": round(min(1.0, max(0.0, level)), 3)})

        def work() -> None:
            try:
                audio = self.listener.record_until(stop_ev, on_level=on_level)
                if self._listen_cancelled:
                    return
                self._set_listening("transcribing")
                self._listen_result = self.listener.transcribe(audio, language)
                r = self._listen_result
                self.emit({"type": "transcript", "text": r.text, "language": r.language,
                           "probability": r.probability, "supported": r.supported})
            except Exception as e:  # noqa: BLE001 — mikrofon ruxsati yo'q, qurilma topilmadi va h.k.
                self._listen_error = mic_error_message(e)
                logging.getLogger("xadicha").warning("mikrofon xatosi: %s", e)
                self.emit({"type": "error", "code": "microphone", "message": self._listen_error})
            finally:
                self._set_listening("idle")

        self.listening = "recording"
        self._listen_thread = threading.Thread(target=work, daemon=True)
        self._listen_thread.start()
        self.emit({"type": "listening", "state": "recording"})
        return "recording"

    def stop_listening(self, timeout: float = 120) -> Transcript | None:
        """Yozishni to'xtatib, matnni qaytaradi. Xato bo'lsa RuntimeError (sababi bilan)."""
        thread = self._listen_thread
        if thread is None:
            raise RuntimeError("Tinglash boshlanmagan.")
        if self._listen_stop:
            self._listen_stop.set()
        thread.join(timeout)
        if self._listen_error:
            raise RuntimeError(self._listen_error)
        return self._listen_result

    def cancel_listening(self) -> None:
        """Yozuvni matnga aylantirmasdan bekor qiladi (favqulodda to'xtatish)."""
        if self._listen_thread and self._listen_thread.is_alive() and self.listening == "recording":
            self._listen_cancelled = True
            if self._listen_stop:
                self._listen_stop.set()

    # --- holat ---
    def status(self) -> dict[str, Any]:
        ok, detail = self.provider.health()
        if self.provider_error:
            ok, detail = False, self.provider_error
        return {
            "os": {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), platform.system()),
            "adapter": self.adapter.name,
            "provider": {"name": self.provider.name, "ok": ok, "detail": detail,
                         "vision": self.provider.supports_vision},
            "config": self.cfg.public(),
            "stats": self.storage.stats(),
            "busy": self.busy,
            "current_task": self.current_task,
            "pending_confirmation": self.pending.public() if self.pending else None,
            "listening": self.listening,
            "capabilities": {
                # Halol holat: faqat ekran surati + vision model. OCR va accessibility daraxti yo'q.
                "screenshot_vision": bool(self.provider.supports_vision and self.agent.screen_fn is not None),
                "ocr": False,
                "accessibility_tree": False,
            },
            "permissions": self.adapter.permissions(),
            "tts": {lang: self.speaker.available(lang) for lang in ("uz", "ru", "en")},
            "stt_engine": self.listener.engine,
        }
