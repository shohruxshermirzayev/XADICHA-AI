"""Google Gemini provayderi — rasmiy `google-genai` SDK orqali.

Ikki xil chaqiruv, ATAYIN alohida bosqichlarda:
  complete()        — agent qarori / reja / suhbat: JSON javob (response_mime_type), rasm bilan ham; vositasiz.
  grounded_answer() — Google Search grounding: faqat matnli javob + grounding_metadata (manbalar, so'rovlar).
Grounding hech qachon harakat (action) qaytarmaydi — desktop harakatlari faqat agentning registry va xavfsizlik
siyosati orqali bajariladi; Gemini hech qanday shell buyrug'ini bajarmaydi.
"""

from __future__ import annotations

import base64
import datetime as _dt
import time
from dataclasses import dataclass, field
from typing import Any

from ..redaction import redact
from ..vision.screen import Screenshot
from .base import LANG_NAMES, LLMProvider, ProviderError

_HEALTH_TTL = 60.0
# Model vaqtincha chetlab o'tiladigan xatolar (keyingi Gemini modeli sinaladi) va muddati, soniya
_MODEL_COOLDOWN = {"server": 120.0, "timeout": 300.0, "config": 600.0, "quota": 60.0}


@dataclass
class GroundedAnswer:
    """Google Search grounding natijasi. Matn o'zgartirilmaydi; manbalar faqat grounding_metadata'dan."""

    text: str
    sources: list[dict[str, str]] = field(default_factory=list)     # [{title, url, domain}]
    queries: list[str] = field(default_factory=list)                # model bajargan qidiruv so'rovlari
    supports: list[dict[str, Any]] = field(default_factory=list)    # [{start, end, text, sources: [i, ...]}]
    search_entry_point: str = ""                                    # Google Search Suggestions (HTML/CSS)
    model: str = ""

    @property
    def grounded(self) -> bool:
        """Model haqiqatan qidiruv bajarganmi (so'rov yoki manba bor)."""
        return bool(self.sources or self.queries)


def _transport_kind(e: BaseException) -> str | None:
    """httpx / httpx2 / requests transport xatolarini kutubxona versiyasiga bog'lanmasdan aniqlaydi."""
    names = {c.__name__ for c in type(e).__mro__}
    if any("Timeout" in n for n in names):
        return "timeout"
    if names & {"TransportError", "NetworkError", "ConnectError", "RemoteProtocolError", "ConnectionError",
                "ProtocolError"} or isinstance(e, OSError):
        return "network"
    return None


def classify_error(e: BaseException, what: str = "Gemini") -> ProviderError:
    """SDK xatosini aniq, kalitsiz ProviderError'ga aylantiradi."""
    try:
        from google.genai import errors as gerr
    except ImportError:  # pragma: no cover
        gerr = None
    # generateContent xatolari (errors.APIError: .code) va Interactions API xatolari (APIStatusError: .status_code)
    status_code = getattr(e, "status_code", None)
    if (gerr is not None and isinstance(e, gerr.APIError)) or isinstance(status_code, int):
        code = int(getattr(e, "code", None) or status_code or 0)
        status = str(getattr(e, "status", "") or "")
        message = str(getattr(e, "message", "") or e)
        details = str(getattr(e, "details", "") or getattr(e, "body", "") or "")
        low = (message + " " + details).lower()
        short = redact(message)[:180]
        if code in (401, 403) or (code == 400 and ("api key" in low or "api_key" in low)):
            return ProviderError(f"{what}: API kaliti noto'g'ri yoki ruxsat yo'q ({code} {status}). "
                                 "backend/.env dagi GEMINI_API_KEY ni tekshiring.", kind="auth")
        if code == 404:
            return ProviderError(f"{what}: model topilmadi yoki mavjud emas ({short}). GEMINI_MODEL ni tekshiring.",
                                 kind="config")
        if code == 429:
            return ProviderError(f"{what}: so'rovlar limiti yoki kvota tugadi (429).", kind="quota")
        if code >= 500:
            err = ProviderError(f"{what}: server xatosi ({code} {status}).", kind="server")
            err.code = code   # type: ignore[attr-defined] — 503 (band) qisqa qayta urinishga loyiq
            return err
        return ProviderError(f"{what}: so'rov rad etildi ({code} {status}: {short}).", kind="request")
    kind = _transport_kind(e)
    if kind == "timeout":
        return ProviderError(f"{what}: javob kutish vaqti tugadi.", kind="timeout")
    if kind == "network":
        return ProviderError(f"{what}: tarmoq xatosi — internet aloqasini tekshiring ({e.__class__.__name__}).",
                             kind="network")
    return ProviderError(f"{what}: kutilmagan xato ({e.__class__.__name__}: {redact(str(e))[:160]}).", kind="error")


class GeminiProvider(LLMProvider):
    name = "gemini"
    supports_vision = True
    supports_grounding = True

    def __init__(self, api_key: str, model: str, timeout_s: float = 20.0, thinking: str = "low", client: Any = None,
                 fallback_models: list[str] | None = None, clock=time.monotonic, retry_delay: float = 0.8):
        if not api_key:
            raise ProviderError("GEMINI_API_KEY o'rnatilmagan (backend/.env).", kind="config")
        if not model:
            raise ProviderError("GEMINI_MODEL bo'sh.", kind="config")
        # Model zanjiri: asosiy model yiqilsa (5xx, timeout, 404, model limiti) — keyingi Gemini modeli
        self.models = [model] + [m for m in (fallback_models or []) if m and m != model]
        self.primary_model = model
        self.model = model               # oxirgi javob bergan model (iz va status uchun)
        self._down: dict[str, tuple[float, str]] = {}    # generatsiya: model → (qachongacha, sabab)
        self._strikes: dict[str, int] = {}                # ketma-ket yiqilishlar — cooldown eksponensial o'sadi
        self._gdown: dict[str, tuple[float, str]] = {}   # grounding alohida (kvotasi boshqa)
        self._clock = clock
        self.retry_delay = retry_delay
        self.thinking = (thinking or "").strip().lower()
        self.timeout_s = timeout_s
        self._health: tuple[float, tuple[bool, str]] | None = None
        if client is not None:
            self._client = client
            return
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise ProviderError("google-genai o'rnatilmagan: pip install -r requirements.txt", kind="config") from e
        # Qayta urinishni SDK emas, biz boshqaramiz: xato bo'lsa darhol zaxira provayderga o'tiladi
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=int(timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1)))

    # --- ichki ---
    def _config(self, **kw: Any) -> Any:
        from google.genai import types

        if self.thinking in ("low", "medium", "high"):
            kw["thinking_config"] = types.ThinkingConfig(thinking_level=self.thinking.upper())
        return types.GenerateContentConfig(**kw)

    def _available_models(self, down: dict[str, tuple[float, str]] | None = None) -> list[str]:
        now = self._clock()
        down = self._down if down is None else down
        return [m for m in self.models if down.get(m, (0.0, ""))[0] <= now]

    def _generate(self, contents: Any, build_config, what: str = "Gemini",
                  down: dict[str, tuple[float, str]] | None = None) -> Any:
        """generate_content + xato tasnifi + model zanjiri. Kalit xatosi kabi umumiy xatoda darhol to'xtaydi;
        model `thinking_level` ni qo'llamasa — bir marta usiz qayta so'raladi. Cheksiz qayta urinish yo'q."""
        down = self._down if down is None else down
        models = self._available_models(down)
        if not models:
            reasons = "; ".join(f"{m}: {r}" for m, (_, r) in down.items())
            raise ProviderError(f"{what}: barcha modellar vaqtincha ishlamayapti ({reasons}).", kind="server")
        last: ProviderError | None = None
        for model in models:
            for attempt in range(2):
                try:
                    cfg = build_config()
                    if self._strikes.get(model):
                        # Yaqinda yiqilgan model — qisqa timeout bilan sinaladi (foydalanuvchi 20 s kutmaydi)
                        from google.genai import types as _t

                        cfg.http_options = _t.HttpOptions(timeout=int(min(self.timeout_s, 5.0) * 1000))
                    resp = self._client.models.generate_content(model=model, contents=contents, config=cfg)
                    self.model = model
                    self._strikes.pop(model, None)
                    return resp
                except Exception as e:  # noqa: BLE001 — har qanday SDK/tarmoq xatosi tasniflanadi
                    err = classify_error(e, f"{what} [{model}]")
                    if attempt == 0 and err.kind == "request" and self.thinking and "think" in str(e).lower():
                        self.thinking = ""   # boshqa model: fikrlash darajasi sozlamasi qo'llanmaydi
                        continue
                    busy = getattr(err, "code", 0) == 503
                    if attempt == 0 and busy:
                        time.sleep(self.retry_delay)   # "high demand" odatda tez o'tadi — bitta qisqa qayta urinish
                        continue
                    last = err
                    if err.kind in _MODEL_COOLDOWN:
                        n = self._strikes[model] = self._strikes.get(model, 0) + 1
                        base = 30.0 if busy else _MODEL_COOLDOWN[err.kind]
                        wait = min(1800.0, base * 2 ** (n - 1))   # takroriy yiqilish — uzoqroq chetlab o'tiladi
                        down[model] = (self._clock() + wait, "503 band" if busy else err.kind)
                        break        # keyingi modelga
                    raise err from e
        assert last is not None
        raise last

    @staticmethod
    def _text(resp: Any, what: str = "Gemini") -> str:
        feedback = getattr(resp, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ProviderError(f"{what}: so'rov xavfsizlik filtri tomonidan bloklandi.", kind="blocked")
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            raise ProviderError(f"{what}: bo'sh javob.", kind="empty")
        text = ""
        content = getattr(cands[0], "content", None)
        for part in (getattr(content, "parts", None) or []):
            if getattr(part, "thought", False):
                continue   # fikrlash qismlari javob emas
            text += getattr(part, "text", None) or ""
        if not text.strip():
            reason = str(getattr(cands[0], "finish_reason", "") or "")
            kind = "blocked" if any(r in reason for r in ("SAFETY", "BLOCKLIST", "PROHIBITED", "RECITATION")) else "empty"
            raise ProviderError(f"{what}: matnsiz javob ({reason or 'sabab noma`lum'}).", kind=kind)
        return text

    # --- LLMProvider ---
    def complete(self, system: str, user: str, screen: Screenshot | None) -> str:
        from google.genai import types

        parts: list[Any] = []
        if screen is not None:
            parts.append(types.Part.from_bytes(data=base64.b64decode(screen.png_base64), mime_type=screen.media_type))
        parts.append(types.Part.from_text(text=user))
        resp = self._generate(
            [types.Content(role="user", parts=parts)],
            lambda: self._config(system_instruction=system, temperature=0.1, max_output_tokens=4096,
                                 response_mime_type="application/json"))
        return self._text(resp)

    supports_streaming = True

    def stream_text(self, system: str, user: str):
        """Oddiy matnli javob bo'laklari (generate_content_stream). Birinchi bo'lakkacha xato bo'lsa — keyingi model;
        bo'lak kelgandan keyin xato — ProviderError (yarim javob almashtirilmaydi)."""
        last: ProviderError | None = None
        for model in self._available_models():
            got = False
            try:
                cfg = self._config(system_instruction=system, temperature=0.4, max_output_tokens=1024)
                for chunk in self._client.models.generate_content_stream(model=model, contents=user, config=cfg):
                    t = ""
                    for cand in (getattr(chunk, "candidates", None) or [])[:1]:
                        for part in (getattr(getattr(cand, "content", None), "parts", None) or []):
                            if not getattr(part, "thought", False):
                                t += getattr(part, "text", None) or ""
                    if t:
                        got = True
                        self.model = model
                        yield t
                if got:
                    self._strikes.pop(model, None)
                    return
                raise ProviderError("Gemini: bo'sh javob.", kind="empty")
            except ProviderError as e:
                if got:
                    raise
                last = e
            except Exception as e:  # noqa: BLE001
                err = classify_error(e, f"Gemini [{model}]")
                if got:
                    raise err from e
                last = err
                if err.kind in _MODEL_COOLDOWN:
                    n = self._strikes[model] = self._strikes.get(model, 0) + 1
                    self._down[model] = (self._clock() + min(1800.0, _MODEL_COOLDOWN[err.kind] * 2 ** (n - 1)), err.kind)
                    continue
                raise err from e
        raise last or ProviderError("Gemini: barcha modellar vaqtincha ishlamayapti.", kind="server")

    def grounded_answer(self, question: str, language: str, conversation: str = "", force: bool = False) -> GroundedAnswer:
        """Google Search grounding bilan javob. JSON rejimi va boshqa vositalar ishlatilmaydi (alohida bosqich)."""
        from google.genai import types

        lang = LANG_NAMES.get(language, "the user's language")
        rule = ("You MUST use Google Search to verify the facts before answering."
                if force else "Use Google Search when the question needs current or external facts.")
        system = (
            "You are XADICHA, a desktop voice assistant. " + rule + " "
            f"Answer in {lang}, in 2-5 short sentences of plain text (no markdown, no lists, no URLs). "
            "Base factual claims only on the search results; if they do not contain the answer, say so. "
            f"Local date and time: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M, %A')}."
        )
        if conversation:
            system += f"\nRecent conversation (for resolving references only):\n{conversation}"
        try:
            resp = self._generate(
                question,
                lambda: self._config(system_instruction=system, temperature=0.2, max_output_tokens=2048,
                                     tools=[types.Tool(google_search=types.GoogleSearch())]),
                what="Gemini (Google Search)", down=self._gdown)
        except ProviderError as e:
            if e.kind == "quota":
                raise ProviderError("Google Search grounding: kvota tugagan yoki tarifingizda mavjud emas (429). "
                                    "Bepul tarifda grounding cheklangan — Google AI Studio'da billing yoqilganini "
                                    "tekshiring. Hozircha oddiy qidiruv (DuckDuckGo/Wikipedia) ishlatiladi.",
                                    kind="quota") from e
            raise
        text = self._text(resp, "Gemini (Google Search)").strip()
        return parse_grounding(resp, text, self.model)

    def warmup(self) -> None:
        """Ishga tushishda kichik so'rov: ishlamayotgan model oldindan aniqlanadi (birinchi buyruq kutmaydi)."""
        try:
            from google.genai import types

            opts = types.HttpOptions(timeout=int(min(self.timeout_s, 8.0) * 1000))
            self._generate("ping", lambda: self._config(max_output_tokens=8, temperature=0.0, http_options=opts))
        except Exception:  # noqa: BLE001 — natija _down/_strikes da; status buni ko'rsatadi
            pass

    def health(self) -> tuple[bool, str]:
        """Kalit va model API'da mavjudligi (models.get — generatsiya xarajatisiz). 60 s keshlanadi."""
        now = time.monotonic()
        if self._health and now - self._health[0] < _HEALTH_TTL:
            return self._health[1]
        try:
            self._client.models.get(model=self.primary_model)
            res: tuple[bool, str] = (True, "ok")
        except Exception as e:  # noqa: BLE001
            res = (False, str(classify_error(e)))
        self._health = (now, res)
        down = {m: r for m, (t, r) in self._down.items() if t > self._clock()}
        if res[0] and down:
            ready = self._available_models()
            note = ", ".join(f"{m} ({r})" for m, r in down.items())
            return (bool(ready), f"vaqtincha ishlamayapti: {note}" + (f" → {ready[0]}" if ready else ""))
        return res

    def invalidate_health(self) -> None:
        self._health = None


def parse_grounding(resp: Any, text: str, model: str = "") -> GroundedAnswer:
    """grounding_metadata → manbalar, so'rovlar, bog'lanishlar, Search Suggestions. Hech narsa to'qilmaydi."""
    cands = getattr(resp, "candidates", None) or []
    gm = getattr(cands[0], "grounding_metadata", None) if cands else None
    out = GroundedAnswer(text=text, model=model)
    if gm is None:
        return out
    remap: dict[int, int] = {}   # grounding_chunks indeksi → sources indeksi (URI'siz bo'laklar tashlanadi)
    for i, ch in enumerate(getattr(gm, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        uri = getattr(web, "uri", None) if web is not None else None
        if not uri:
            continue
        title = getattr(web, "title", None) or getattr(web, "domain", None) or uri
        remap[i] = len(out.sources)
        out.sources.append({"title": str(title), "url": str(uri), "domain": str(getattr(web, "domain", None) or title)})
    out.queries = [str(q) for q in (getattr(gm, "web_search_queries", None) or []) if q]
    for sp in (getattr(gm, "grounding_supports", None) or []):
        seg = getattr(sp, "segment", None)
        idx = [remap[int(i)] for i in (getattr(sp, "grounding_chunk_indices", None) or []) if int(i) in remap]
        if seg is None or not idx:
            continue
        out.supports.append({"start": getattr(seg, "start_index", None), "end": getattr(seg, "end_index", None),
                             "text": getattr(seg, "text", "") or "", "sources": idx})
    entry = getattr(gm, "search_entry_point", None)
    out.search_entry_point = str(getattr(entry, "rendered_content", "") or "") if entry is not None else ""
    return out
