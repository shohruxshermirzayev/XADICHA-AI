"""Ilova xizmati: agent, nutq, tasdiqlar va hodisalarni bir joyda boshqaradi (API va CLI uchun)."""

from __future__ import annotations

import logging
import re
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
from .speech.stt import Endpointer, Listener, Transcript
from .understand import understand
from .conversation import Conversation, Turn
from .lang import refine_asr_language
from .speech.tts import Speaker
from .storage import Storage


_SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "sk-***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1***"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|parol)\s*[=:]\s*)\S+"), r"\1***"),
    (re.compile(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]{32,}"), "data:image/***"),
]


def redact(text: str) -> str:
    """Log va xato matnlaridan kalit, token va rasm ma'lumotlarini olib tashlaydi."""
    for pat, rep in _SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001
            pass
        return True


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
    h.addFilter(RedactFilter())
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


def microphone_state() -> dict[str, str]:
    """Kirish qurilmasi bormi (yozmasdan tekshiradi). Ruxsat faqat yozish paytida aniqlanadi."""
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        name = dev.get("name", "") if isinstance(dev, dict) else ""
        return {"state": "not_tested", "detail": f"qurilma: {name}" if name else "kirish qurilmasi bor"}
    except Exception as e:  # noqa: BLE001
        return {"state": "unavailable", "detail": mic_error_message(e)}


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
                 storage: Storage | None = None, screen_fn=None, confirm_timeout: float = 120,
                 ocr=None, accessibility=None):
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
        self.stt_ready = False
        self.stt_error = ""
        self.confirm_timeout = confirm_timeout
        self.listeners: list[Callable[[dict[str, Any]], None]] = []
        # Har bir hodisa tartib raqami oladi. /api/status ham joriy raqamni qaytaradi — interfeys eskirgan
        # HTTP javobi yangi WebSocket hodisasini bosib qo'ymasligini shu bilan tekshiradi.
        self._seq = 0
        self.instance = uuid.uuid4().hex[:8]   # backend qayta ishga tushsa seq 0 dan boshlanadi — buni ajratish uchun
        self._seq_lock = threading.Lock()
        self.speaking = False
        self.pending: PendingConfirmation | None = None
        self.current_task: str | None = None
        self._run_lock = threading.Lock()
        self.listening = "idle"            # "idle" | "recording" | "transcribing" — qayta ulanishda tiklash uchun
        self._listen_stop: threading.Event | None = None
        self._listen_thread: threading.Thread | None = None
        self._listen_result: Transcript | None = None
        self._listen_error = ""
        self._listen_cancelled = False
        self.listen_handled = False

        from .vision.context import NullAccessibility, NullOCR, make_accessibility, make_ocr

        real_os = self.adapter.name in ("macos", "windows")
        self.ocr = ocr if ocr is not None else (make_ocr() if real_os else NullOCR("dry-run: ekran yo'q"))
        self.ax = accessibility if accessibility is not None else (
            make_accessibility() if real_os else NullAccessibility("dry-run: ekran yo'q"))
        self.screen_error = ""
        if screen_fn is None and real_os:
            screen_fn = self._capture_with_context
        self.agent = Agent(cfg, self.provider, self.adapter, self.storage, confirm=self._confirm,
                           on_event=self.emit, screen_fn=screen_fn)
        self.agent.text_context = self._context_usable()
        self.conversation = self._restore_conversation()
        self.agent.conversation = self.conversation
        self._voice_trace: list[dict[str, Any]] = []

    # --- suhbat ---
    def _restore_conversation(self) -> Conversation:
        """Oxirgi suhbatni tiklaydi: navbatlar matni va (vazifalardan) obyektlar — "uni yana och" ishlashi uchun."""
        sid = self.storage.latest_session()
        conv = Conversation(sid)
        if not sid:
            return conv
        for t in self.storage.list_turns(sid, 40):
            if t["role"] == "assistant" and t.get("task_id"):
                task = self.storage.get_task(t["task_id"])
                if task is not None:
                    conv.add_task(task)
                    continue
            conv.turns.append(Turn(t["role"], t["text"], t.get("lang") or "", t.get("task_id"), t.get("status"), t["ts"]))
        return conv

    def new_conversation(self) -> str:
        self.conversation.clear()
        self.agent.conversation = self.conversation
        self.emit({"type": "conversation_reset", "session_id": self.conversation.session_id})
        return self.conversation.session_id

    def conversation_public(self) -> dict[str, Any]:
        return {"session_id": self.conversation.session_id,
                "turns": self.storage.list_turns(self.conversation.session_id, 200)}

    # --- ekran konteksti ---
    def _context_usable(self) -> bool:
        return self.ocr.availability()[0] != "unavailable" or self.ax.availability()[0] != "unavailable"

    def _capture_with_context(self):
        """Ekran surati + (bo'lsa) OCR va accessibility matni. Surat diskka yozilmaydi va logga chiqmaydi."""
        from .vision.context import summarize
        from .vision.screen import capture_image, encode

        try:
            img, lw, lh = capture_image(self.adapter.screen_size())
        except Exception as e:  # noqa: BLE001 — Screen Recording ruxsati yo'q va h.k.
            self.screen_error = f"{e.__class__.__name__}: {e}"
            raise
        self.screen_error = ""
        shot = encode(img, lw, lh, self.cfg.screen_max_side)
        texts, elements = [], []
        if self.ocr.availability()[0] != "unavailable":
            try:
                texts = self.ocr.recognize(img, (lw, lh))
            except Exception:  # noqa: BLE001
                logging.getLogger("xadicha").exception("OCR xatosi")
        if self.ax.availability()[0] != "unavailable":
            try:
                elements = self.ax.snapshot()
            except Exception:  # noqa: BLE001
                logging.getLogger("xadicha").exception("Accessibility xatosi")
        shot.context = summarize(texts, elements, factor=1.0 / shot.scale)
        return shot

    def capabilities(self, health: tuple[bool, str] | None = None) -> dict[str, dict[str, str]]:
        """Halol holat: available | unavailable | not_tested | not_implemented. Sozlama mavjudligi — "yoqilgan" emas."""
        def cap(state: str, detail: str = "") -> dict[str, str]:
            return {"state": state, "detail": detail}

        real_os = self.adapter.name in ("macos", "windows")
        ok, detail = health if health is not None else self.provider.health()
        if self.provider_error:
            ok, detail = False, self.provider_error
        if not self.provider.supports_vision:
            vision = cap("unavailable", f"{self.provider.name}: model ekranni ko'rmaydi")
        elif not ok:
            vision = cap("unavailable", detail)
        else:
            vision = cap("not_tested", "model ulangan; ekran tushunish sifati o'lchanmagan")
        ocr_state, ocr_detail = self.ocr.availability()
        ax_state, ax_detail = self.ax.availability()
        mic = microphone_state()
        tts_any = any(self.speaker.available(lang) for lang in ("uz", "ru", "en"))
        return {
            "os_adapter": cap("not_tested", f"{self.adapter.name}: real qurilmada avtomatik sinalmagan") if real_os
            else cap("unavailable", "dry-run: harakatlar bajarilmaydi (simulyatsiya)"),
            "screenshot": cap("unavailable", self.screen_error) if self.screen_error
            else cap("not_tested", "mss orqali; real ekranda sinalmagan") if real_os
            else cap("unavailable", "dry-run: ekran yo'q"),
            "vision_model": vision,
            "ocr": {"state": ocr_state, "detail": ocr_detail},
            "accessibility_tree": {"state": ax_state, "detail": ax_detail},
            "microphone": mic,
            "stt": cap("not_tested" if self.stt_ready else "unavailable",
                       f"{self.listener.engine} · {self.cfg.whisper_model}" if self.stt_ready
                       else (self.stt_error or "model hali yuklanmagan")),
            "tts": cap("not_tested", f"{self.cfg.tts_engine}: " + ", ".join(
                f"{lg}={self.speaker.voice_for(lg) or '—'}" for lg in ("uz", "ru", "en")))
            if (self.cfg.tts_enabled and tts_any)
            else cap("unavailable", "o'chirilgan" if not self.cfg.tts_enabled else "ovoz topilmadi"),
            "windows_ui_automation": cap("not_implemented", "rejada"),
        }

    def warmup(self) -> None:
        """Model va nutqni aniqlashni fonda oldindan yuklash — birinchi buyruq tezroq bo'ladi."""
        def work() -> None:
            self.provider.warmup()
            try:
                self.listener.warmup()
                self.stt_ready = getattr(self.listener, "_model", None) is not None or self.listener.engine == "mlx"
            except Exception as e:  # noqa: BLE001
                self.stt_error = f"{e.__class__.__name__}: {e}"
            self.emit({"type": "warm", "stt_engine": self.listener.engine})
        threading.Thread(target=work, daemon=True).start()

    # --- hodisalar ---
    def subscribe(self, fn: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self.listeners.append(fn)
        return lambda: self.listeners.remove(fn) if fn in self.listeners else None

    def emit(self, event: dict[str, Any]) -> None:
        with self._seq_lock:
            self._seq += 1
            event = {**event, "seq": self._seq}
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:  # noqa: BLE001
                pass

    # --- yagona holat ---
    @property
    def phase(self) -> str:
        """idle | running | awaiting_confirmation | speaking — interfeysdagi barcha joylar shundan foydalanadi."""
        if self.pending is not None:
            return "awaiting_confirmation"
        if self.speaking:
            return "speaking"
        if self.busy:
            return "running"
        return "idle"

    def state_snapshot(self) -> dict[str, Any]:
        return {"busy": self.busy, "phase": self.phase, "current_task": self.current_task,
                "listening": self.listening}

    def _emit_state(self) -> None:
        self.emit({"type": "state", **self.state_snapshot()})

    # --- tasdiq ---
    def _confirm(self, task: TaskRecord, action: Action, risk: RiskLevel, reason: str) -> bool | str:
        p = PendingConfirmation(task.id, action, risk, reason, self.confirm_timeout)
        self.pending = p
        self.emit({"type": "confirm_request", **p.public()})
        self._emit_state()
        if not p.event.wait(self.confirm_timeout):
            p.resolve("timeout")
        self.pending = None
        self.emit({"type": "confirm_resolved", "id": p.id, "task_id": task.id,
                   "approved": p.approved, "outcome": p.outcome})
        self._emit_state()
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
            self.storage.save_turn(self.conversation.session_id, self.conversation.add_user(instruction, language))
            voice_trace, self._voice_trace = self._voice_trace, []
            try:
                task = self.agent.run(instruction, language, mode, clear_cancel=not _locked)
            finally:
                unsub()
            if voice_trace:
                task.trace = voice_trace + task.trace   # ovoz bosqichlari (yozish, endpoint, ASR) vazifa iziga qo'shiladi
            self.storage.save_turn(self.conversation.session_id, self.conversation.add_task(task))
            if speak and task.final_message:
                self.speaking = True
                self._emit_state()
                t_tts = time.perf_counter()
                try:
                    spoken = self.speaker.say(task.final_message, task.language)
                finally:
                    self.speaking = False
                task.trace.append({"stage": "tts", "ms": int((time.perf_counter() - t_tts) * 1000), "ok": bool(spoken),
                                   "provider": self.speaker.engine})
                self.storage.save_task(task)
                self.emit({"type": "spoken", "task_id": task.id, "text": task.final_message, "audio": spoken})
            return task
        finally:
            self.current_task = None
            self.speaking = False
            self._run_lock.release()
            # Vazifa to'liq tugadi (ovoz ham) — interfeys "band" holatida osilib qolmasligi uchun aniq e'lon
            self._emit_state()

    def start_task(self, instruction: str, language: str = "uz", mode: Mode = Mode.multimodal) -> None:
        # Qulf shu yerda olinadi: ikki tez so'rov ikkalasi ham "bo'sh" deb ko'rib, ikki vazifa boshlamasligi uchun
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Boshqa vazifa bajarilmoqda.")
        self.agent._cancel.clear()   # shu paytdan keyin bosilgan "To'xtatish" vazifaga yetib boradi
        try:
            threading.Thread(target=self._safe_run, args=(instruction, language, mode), daemon=True).start()
        except Exception:
            self._run_lock.release()
            raise
        self._emit_state()

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
        self._emit_state()

    def start_listening(self, language: str | None = None, auto: bool = False,
                        mode: Mode = Mode.multimodal, force_language: bool = False) -> str:
        """language — tanlangan til: odatda "prior" (ustunlik), force_language=True bo'lsa — majburiy (CLI --lang)."""
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
        self.listen_handled = False
        endpointer = Endpointer() if auto else None
        last = [0.0]

        def on_level(level: float) -> None:
            now = time.monotonic()
            if now - last[0] >= 0.066:   # ~15 marta/soniya — WebSocket'ni to'ldirmaslik uchun
                last[0] = now
                self.emit({"type": "mic_level", "level": round(min(1.0, max(0.0, level)), 3)})

        def work() -> None:
            try:
                t_rec = time.perf_counter()
                if endpointer is not None:
                    audio = self.listener.record_until(stop_ev, on_level=on_level, endpointer=endpointer)
                else:
                    audio = self.listener.record_until(stop_ev, on_level=on_level)
                trace = [{"stage": "audio_capture", "ms": int((time.perf_counter() - t_rec) * 1000), "ok": True}]
                if endpointer is not None and endpointer.reason:
                    trace.append({"stage": "vad_endpoint", "ms": int(endpointer.endpoint_delay_s * 1000), "ok": True,
                                  "reason": endpointer.reason})
                if self._listen_cancelled:
                    return
                self._set_listening("transcribing")
                t_asr = time.perf_counter()
                if force_language:
                    self._listen_result = self.listener.transcribe(audio, language)
                else:
                    self._listen_result = self.listener.transcribe(audio, None, prior=language)
                r = self._listen_result
                trace.append({"stage": "asr", "ms": int((time.perf_counter() - t_asr) * 1000), "ok": bool(r.text),
                              "provider": getattr(self.listener, "engine", None),
                              "model": getattr(self.listener, "model_name", None)})
                if r.text and not force_language:
                    r.language = refine_asr_language(r.text, r.language, r.probability or None, language)
                self._voice_trace = trace
                if r.text:
                    self.emit({"type": "transcript", "text": r.text, "language": r.language,
                               "probability": r.probability, "supported": r.supported})
                if auto:
                    self._auto_handle(r, mode)
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
        self._emit_state()
        return "recording"

    def _auto_handle(self, r: Transcript, mode: Mode) -> None:
        """Avtomatik rejim: aniq buyruq — darhol bajariladi; noaniq — aniqlashtirish; bo'sh — hech narsa."""
        self.listen_handled = True
        if not r.text:
            self.emit({"type": "voice_result", "status": "empty"})
            return
        if not r.supported:
            self.emit({"type": "voice_result", "status": "unsupported", "language": r.language})
            return
        analysis = understand(r.text, r.language, r.asr_confidence, llm_available=self.provider.name != "rules")
        if analysis.needs_clarification:
            # Aytilgani aniq emas — o'zicha hech narsa qilinmaydi, foydalanuvchi tanlaydi
            self.emit({"type": "clarify", "text": r.text, "language": r.language,
                       "asr_confidence": r.asr_confidence, "analysis": analysis.public()})
            return
        try:
            self.start_task(r.text, r.language, mode)
            self.emit({"type": "voice_result", "status": "started", "text": r.text})
        except RuntimeError as e:
            self.emit({"type": "error", "message": str(e)})

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
        # seq avval o'qiladi: javobdagi ma'lumot shu raqamdagi holatdan eskiroq bo'lmaydi
        seq = self._seq
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
            "phase": self.phase,
            "seq": seq,
            "instance": self.instance,
            "current_task": self.current_task,
            "pending_confirmation": self.pending.public() if self.pending else None,
            "listening": self.listening,
            "capabilities": self.capabilities((ok, detail)),
            "permissions": self.adapter.permissions(),
            "tts": {lang: self.speaker.available(lang) for lang in ("uz", "ru", "en")},
            "stt_engine": self.listener.engine,
        }
