"""Ilova xizmati: agent, nutq, tasdiqlar va hodisalarni bir joyda boshqaradi (API va CLI uchun)."""

from __future__ import annotations

import logging
import os
import re

import numpy as np
from pathlib import Path
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


from .redaction import redact  # noqa: E402 — tashqi kod `from xadicha.service import redact` dan foydalanadi


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
            if record.exc_info and not record.exc_text:
                # Traceback ham yashiriladi (formatter tayyor exc_text'ni ishlatadi)
                record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
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
        logging.getLogger("xadicha").info(
            "provayder: %s%s · qidiruv: %s%s", cfg.provider,
            f" ({cfg.gemini_model}, zaxira: {cfg.fallback})" if cfg.provider == "gemini" else "",
            cfg.search_mode, f" · ogohlantirish: {'; '.join(cfg.warnings)}" if cfg.warnings else "")
        from .speech import tts as _tts

        _tts.TTS_CACHE_DIR = cfg.db_path.parent / "tts_cache"   # qisqa javoblar keshi (takroriy javob — darhol)
        self.speaker = Speaker(cfg.tts_engine, cfg.tts_rate,
                               {"uz": cfg.voice_uz, "ru": cfg.voice_ru, "en": cfg.voice_en}, cfg.tts_enabled)
        self.listener = Listener(cfg.whisper_model, cfg.stt_engine)
        from .speech.recognizer import make_recognizer

        self.stt = make_recognizer(cfg, self.listener)   # Gemini Transcribe / Whisper (provayder metadata bilan)
        from .settings import SettingsStore

        self.settings_store = SettingsStore(cfg.db_path.parent / "settings.json")
        self.apply_settings(self.settings_store.load(), persist=False)
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

        def ms(t: float) -> int:
            return int((time.perf_counter() - t) * 1000)

        t0 = time.perf_counter()
        try:
            img, lw, lh = capture_image(self.adapter.screen_size())
        except Exception as e:  # noqa: BLE001 — Screen Recording ruxsati yo'q va h.k.
            self.screen_error = f"{e.__class__.__name__}: {e}"
            raise
        timings = {"capture": ms(t0)}
        self.screen_error = ""
        t1 = time.perf_counter()
        shot = encode(img, lw, lh, self.cfg.screen_max_side)
        timings["encode"] = ms(t1)
        texts, elements = [], []
        # Vision model rasmni o'zi o'qiydi — har qadamda to'liq ekran OCR ortiqcha (kechikish); faqat matnli model uchun
        need_ocr = not self.provider.supports_vision or os.getenv("XADICHA_OCR_WITH_VISION", "") in ("1", "true")
        if not need_ocr:
            timings["ocr_skipped"] = 1
        if need_ocr and self.ocr.availability()[0] != "unavailable":
            t2 = time.perf_counter()
            try:
                texts = self.ocr.recognize(img, (lw, lh))
            except Exception:  # noqa: BLE001
                logging.getLogger("xadicha").exception("OCR xatosi")
            timings["ocr"] = ms(t2)
        if self.ax.availability()[0] != "unavailable":
            t3 = time.perf_counter()
            try:
                elements = self.ax.snapshot()
            except Exception:  # noqa: BLE001
                logging.getLogger("xadicha").exception("Accessibility xatosi")
            timings["ax"] = ms(t3)
        shot.context = summarize(texts, elements, factor=1.0 / shot.scale)
        shot.timings = timings
        return shot

    def screen_snapshot(self, preview: bool = True, max_items: int = 80) -> dict[str, Any]:
        """Foydalanuvchi so'raganda ekran holati: old plandagi ilova, oyna sarlavhasi, kichik ko'rinish, OCR va
        accessibility elementlari. Hech narsa diskka yozilmaydi va logga chiqmaydi; ruxsat bo'lmasa — sababi bilan."""
        from .vision.screen import capture_image, encode

        real_os = self.adapter.name in ("macos", "windows")
        out: dict[str, Any] = {"available": real_os, "captured_at": time.time(), "app": None, "window": None,
                               "preview": None, "size": None, "timings": {}, "error": None,
                               "ocr": {"state": self.ocr.availability()[0], "lines": []},
                               "ax": {"state": self.ax.availability()[0], "elements": []}}
        if not real_os:
            out["error"] = "dry-run: ekran yo'q (simulyatsiya)"
            return out
        out["app"] = self.adapter.frontmost_app() or None
        title = getattr(self.adapter, "front_window_title", None)
        out["window"] = (title() if callable(title) else "") or None
        t0 = time.perf_counter()
        try:
            img, lw, lh = capture_image(self.adapter.screen_size())
        except Exception as e:  # noqa: BLE001 — Screen Recording ruxsati yo'q va h.k.
            self.screen_error = f"{e.__class__.__name__}: {e}"
            out["error"] = self.screen_error
            return out
        out["timings"]["capture_ms"] = int((time.perf_counter() - t0) * 1000)
        out["size"] = [lw, lh]
        if preview:
            shot = encode(img, lw, lh, 640)   # kichik ko'rinish — faqat javobda, diskka yozilmaydi
            out["preview"] = "data:image/jpeg;base64," + shot.png_base64
        if out["ocr"]["state"] != "unavailable":
            t1 = time.perf_counter()
            try:
                boxes = sorted(self.ocr.recognize(img, (lw, lh)), key=lambda b: (b.y, b.x))[:max_items]
                out["ocr"]["lines"] = [{"text": b.text[:160], "confidence": round(b.confidence, 2),
                                        "x": b.x, "y": b.y, "w": b.w, "h": b.h} for b in boxes]
            except Exception as e:  # noqa: BLE001
                out["ocr"]["error"] = e.__class__.__name__
            out["timings"]["ocr_ms"] = int((time.perf_counter() - t1) * 1000)
        if out["ax"]["state"] != "unavailable":
            t2 = time.perf_counter()
            try:
                out["ax"]["elements"] = [{"role": e.role, "name": e.name[:120], "enabled": e.enabled,
                                          "x": e.x, "y": e.y, "w": e.w, "h": e.h} for e in self.ax.snapshot()[:max_items]]
            except Exception as e:  # noqa: BLE001
                out["ax"]["error"] = e.__class__.__name__
            out["timings"]["ax_ms"] = int((time.perf_counter() - t2) * 1000)
        return out

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
            "stt": cap("not_tested", f"Gemini ({self.cfg.gemini_stt_live_model if self.stream_available() else self.cfg.gemini_stt_model})"
                       f" · zaxira Whisper {self.cfg.whisper_model}" + ("" if self.stt_ready else " (kerak bo'lganda yuklanadi)"))
            if (self.stt.gemini is not None and not self.cfg.offline_mode and self.cfg.stt_provider != "whisper")
            else cap("not_tested" if self.stt_ready else "unavailable",
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
            if self.stream_available():
                try:   # oldindan ochilgan Live Transcription sessiyasi — buyruqda ulanish kutilmaydi
                    self._ensure_stt_pool()
                except Exception as e:  # noqa: BLE001
                    logging.getLogger("xadicha").info("oqimli STT pool ochilmadi: %s", redact(str(e))[:120])
            self.provider.warmup()
            # Gemini STT ishlayotgan bo'lsa Whisper faqat zaxira — oldindan yuklanmaydi: CPU'da model yuklash 1–2 daqiqa
            # boshqa so'rovlarni sekinlashtirardi (o'lchov). Oflayn / whisper rejimida — avvalgidek oldindan yuklanadi.
            if self.stt.gemini is not None and self.cfg.stt_provider != "whisper" and not self.cfg.offline_mode:
                self.emit({"type": "warm", "stt_engine": self.listener.engine, "whisper": "lazy"})
                return
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

    # --- ovozli so'rov kechikishi: mikrofon boshidan har bir bosqichgacha (ms) ---
    _vt0: float | None = None
    _vmarks: dict[str, int] = {}

    def _vmark(self, name: str, at_ms: int | None = None) -> None:
        if self._vt0 is not None and name not in self._vmarks:
            self._vmarks[name] = at_ms if at_ms is not None else int((time.perf_counter() - self._vt0) * 1000)

    def _vfinish(self, task: Any = None) -> None:
        """Ovozli so'rov yakunlandi — kechikishlar xulosasi (haqiqiy o'lchov) hodisa va vazifa ma'lumotiga."""
        if self._vt0 is None:
            return
        m = dict(self._vmarks)
        self._vt0, self._vmarks = None, {}
        summary = {"marks": m, "ttf_partial": m.get("first_partial"), "ttf_final": m.get("final_transcript"),
                   "tt_first_action": m.get("first_action"), "tt_response_text": m.get("response_text"),
                   "tt_response_audio": m.get("response_audio"),
                   "e2e": m.get("response_audio") or m.get("response_text"), "stt": self._vstt}
        if task is not None:
            task.data["latency"] = summary
            self.storage.save_task(task)
        self.emit({"type": "voice_latency", "task_id": getattr(task, "id", None), **summary})

    _stream_tts_task: str | None = None

    def emit(self, event: dict[str, Any]) -> None:
        if event.get("type") == "response_sentence" and event.get("task_id") == self._stream_tts_task:
            if self.speaker.stream_push(str(event.get("text", "")), str(event.get("lang") or "uz")):
                self.speaking = True
                self._vmark("response_audio")   # birinchi gap ovoz navbatiga tushdi (javob hali yozilmoqda)
            return   # ichki hodisa — interfeysga yuborilmaydi
        if event.get("type") == "response_partial":
            self._vmark("first_response_text")
        if self._vt0 is not None:
            k = event.get("type")
            if k == "step_started":
                self._vmark("first_action")
            elif k == "step_finished":
                self._vmark("action_done")
            elif k == "task_finished":
                self._vmark("response_text")
        if isinstance(event.get("message"), str):
            event = {**event, "message": redact(event["message"])}   # xato matnida kalit bo'lsa — interfeysga chiqmaydi
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
                    if speak and self.cfg.tts_enabled:
                        self._stream_tts_task = e["task_id"]   # oqimli javob gaplari darhol ovozga

            unsub = self.subscribe(track)
            self.speaker.stop()
            self._stream_tts_task = None
            self.storage.save_turn(self.conversation.session_id, self.conversation.add_user(instruction, language))
            voice_trace, self._voice_trace = self._voice_trace, []
            try:
                task = self.agent.run(instruction, language, mode, clear_cancel=not _locked)
            finally:
                unsub()
            if voice_trace:
                task.trace = voice_trace + task.trace   # ovoz bosqichlari (yozish, endpoint, ASR) vazifa iziga qo'shiladi
            self.storage.save_turn(self.conversation.session_id, self.conversation.add_task(task))
            streamed = bool(task.data.get("streamed")) and self._stream_tts_task == task.id
            self._stream_tts_task = None
            if streamed:
                self.speaker.stream_end()   # gaplar allaqachon ovozda — qayta aytilmaydi
                self.speaking = False
            if speak and task.final_message and not streamed:
                self.speaking = True
                self._emit_state()
                t_tts = time.perf_counter()
                try:
                    spoken = self.speaker.say(task.final_message, task.language)
                    if spoken:
                        self._vmark("response_audio")   # birinchi ovoz bo'lagi ijroga berildi
                finally:
                    self.speaking = False
                task.trace.append({"stage": "tts", "ms": int((time.perf_counter() - t_tts) * 1000), "ok": bool(spoken),
                                   "provider": self.speaker.engine})
                self.storage.save_task(task)
                self.emit({"type": "spoken", "task_id": task.id, "text": task.final_message, "audio": spoken})
            self._vfinish(task)
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

    # --- ish vaqtidagi sozlamalar (maxfiy emas) ---
    def settings_public(self) -> dict[str, Any]:
        from .settings import input_devices

        c = self.cfg
        return {
            "values": {"search_mode": c.search_mode, "stt_provider": c.stt_provider, "live_enabled": c.live_enabled,
                       "live_barge_in": c.live_barge_in, "uz_script": c.uz_script,
                       "tts_enabled": c.tts_enabled, "tts_rate": c.tts_rate, "offline_mode": c.offline_mode,
                       "auto_language": c.auto_language, "microphone": c.microphone,
                       "vocabulary": list(getattr(self, "_vocab_extra", [])),
                       "corrections": dict(self.stt.vocabulary.corrections)},
            "readonly": {"provider": c.provider, "gemini_model": c.gemini_model,
                         "gemini_fallback_models": c.gemini_fallback_models, "ollama_model": c.ollama_model,
                         "whisper_model": c.whisper_model, "gemini_stt_model": c.gemini_stt_model,
                         "live_model": c.live_model, "has_gemini_key": bool(c.gemini_api_key),
                         "vocabulary_file": c.vocabulary_file},
            "options": {"microphones": input_devices()},
        }

    def apply_settings(self, new: Any, persist: bool = True) -> dict[str, Any]:
        """Tekshirilgan sozlamalarni darhol qo'llaydi (qayta ishga tushirmasdan) va saqlaydi."""
        from .settings import RuntimeSettings
        from .speech.recognizer import DEFAULT_TERMS, Vocabulary, make_recognizer

        upd: RuntimeSettings = new if isinstance(new, RuntimeSettings) else RuntimeSettings.model_validate(new)
        c = self.cfg
        if upd.search_mode is not None:
            c.search_mode = upd.search_mode
        if upd.stt_provider is not None and upd.stt_provider != c.stt_provider:
            c.stt_provider = upd.stt_provider
            vocab = self.stt.vocabulary
            self.stt = make_recognizer(c, self.listener)   # kerak bo'lsa Gemini Transcribe mijozi yaratiladi
            self.stt.vocabulary = vocab
        if upd.live_enabled is not None:
            c.live_enabled = upd.live_enabled
            if not upd.live_enabled and self.live is not None and self.live.active:
                self.live.stop()
        if upd.live_barge_in is not None:
            c.live_barge_in = upd.live_barge_in
            if self.live is not None:
                self.live.barge_in = upd.live_barge_in   # faol sessiyaga darhol
        if upd.uz_script is not None:
            c.uz_script = upd.uz_script
        if upd.tts_enabled is not None:
            c.tts_enabled = self.speaker.enabled = upd.tts_enabled
        if upd.tts_rate is not None:
            c.tts_rate = self.speaker.rate = upd.tts_rate
        if upd.auto_language is not None:
            c.auto_language = upd.auto_language
        if upd.microphone is not None:
            c.microphone = upd.microphone
            self.listener.device = upd.microphone or None
        if upd.vocabulary is not None or upd.corrections is not None:
            base = Vocabulary.load(Path(c.vocabulary_file)) if c.vocabulary_file else Vocabulary()
            if upd.vocabulary is not None:
                self._vocab_extra = upd.vocabulary
            extra = getattr(self, "_vocab_extra", [])
            corr = {**base.corrections, **(upd.corrections if upd.corrections is not None else self.stt.vocabulary.corrections)}
            self.stt.vocabulary = Vocabulary(list(dict.fromkeys(base.terms + DEFAULT_TERMS + extra))[:1000], corr,
                                             "settings")
        if upd.offline_mode is not None:
            c.offline_mode = upd.offline_mode
        # Oflayn rejim: bulut provayderlari chetlab o'tiladi (Ollama + Whisper), Live to'xtatiladi
        if hasattr(self.provider, "offline"):
            self.provider.offline = c.offline_mode
        self.stt.offline = c.offline_mode
        if c.offline_mode and self.live is not None and self.live.active:
            self.live.stop()
        if persist:
            merged = self.settings_store.load().model_dump(exclude_none=True)
            merged.update(upd.model_dump(exclude_none=True))
            self.settings_store.save(RuntimeSettings.model_validate(merged))
            logging.getLogger("xadicha").info("sozlamalar yangilandi: %s", sorted(upd.model_dump(exclude_none=True)))
            self.emit({"type": "settings", **self.settings_public()["values"]})
        return self.settings_public()

    # --- Gemini Live: real vaqtli ovozli suhbat ---
    live = None   # LiveSession | None

    def live_available(self) -> tuple[bool, str]:
        if not self.cfg.live_enabled:
            return False, "Gemini Live o'chirilgan (GEMINI_LIVE=0 yoki sozlamalar)."
        if getattr(self.cfg, "offline_mode", False):
            return False, "Oflayn rejim — bulut ovozi ishlatilmaydi."
        if not self.cfg.gemini_api_key:
            return False, "GEMINI_API_KEY o'rnatilmagan — Gemini Live mavjud emas."
        return True, "ok"

    def start_live(self, session_factory=None) -> dict[str, Any]:
        """Live suhbatni boshlaydi. Mavjud bo'lmasa — RuntimeError (interfeys oddiy ovoz yo'liga qaytadi)."""
        ok, why = self.live_available()
        if not ok and session_factory is None:
            raise RuntimeError(why)
        if self.live is not None and self.live.active:
            return self.live.info()
        self.cancel_listening()
        self.speaker.stop()
        from .speech.live import LiveSession

        from .speech.live import SoundDeviceIO

        mic = self.cfg.microphone or None
        factory = session_factory or (lambda **kw: LiveSession(self.cfg.gemini_api_key, self.cfg.live_model,
                                                               audio_factory=lambda: SoundDeviceIO(mic), **kw))
        self.live = factory(emit=self._live_event, run_command=self._live_command, voice=self.cfg.live_voice,
                            vocabulary=self.stt.vocabulary.terms, barge_in=self.cfg.live_barge_in)
        self.live.start()
        logging.getLogger("xadicha").info("Gemini Live boshlandi (%s)", self.cfg.live_model)
        return self.live.info()

    def stop_live(self) -> dict[str, Any]:
        if self.live is not None:
            self.live.stop()
            logging.getLogger("xadicha").info("Gemini Live to'xtatildi")
        return self.live.info() if self.live is not None else {"active": False, "state": "idle"}

    def _live_event(self, e: dict[str, Any]) -> None:
        if e.get("type") == "live_turn":
            # Live navbatlari ham suhbat kontekstiga yoziladi ("uni yana och" va keyingi model chaqiruvlari uchun)
            from .conversation import Turn
            from .lang import detect_text_language

            for role in ("user", "assistant"):
                text = str(e.get(role) or "").strip()
                if text:
                    turn = Turn(role, redact(text)[:2000], detect_text_language(text).lang)
                    self.conversation.turns.append(turn)
                    self.storage.save_turn(self.conversation.session_id, turn)
        self.emit(e)

    def _live_command(self, instruction: str) -> dict[str, Any]:
        """Live modeli so'ragan desktop buyrug'i — mavjud agent orqali (router, xavfsizlik, tasdiq, registry)."""
        from .lang import detect_text_language

        if not self._run_lock.acquire(blocking=False):
            return {"status": "busy", "result": "Boshqa vazifa bajarilmoqda — tugashini kuting."}
        self.agent._cancel.clear()
        try:
            task = self.run_task(instruction, detect_text_language(instruction).lang, Mode.multimodal,
                                 speak=False, _locked=True)
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "result": redact(f"{e.__class__.__name__}: {e}")[:200]}
        return {"status": task.status.value, "result": task.final_message,
                "steps": [{"action": st.action.describe(), "status": st.status.value} for st in task.steps][:8]}

    def stop(self) -> None:
        """Favqulodda to'xtatish: joriy vazifa, kutilayotgan tasdiq, ovoz va mikrofon."""
        self.agent.stop()
        self.speaker.stop()
        if self.live is not None and self.live.active:
            self.live.stop()
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
        if not self.cfg.auto_language and language in ("uz", "ru", "en"):
            force_language = True
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
                self._vt0, self._vmarks, self._vstt = t_rec, {}, ""
                streamed = self._stream_listen(stop_ev, on_level, auto, language, force_language, mode)
                if isinstance(streamed, str) and streamed == "done":
                    return
                if isinstance(streamed, np.ndarray):   # oqim yiqildi — buferdagi audio oddiy yo'lga (yo'qolmaydi)
                    audio = streamed
                elif endpointer is not None:
                    audio = self.listener.record_until(stop_ev, on_level=on_level, endpointer=endpointer)
                else:
                    audio = self.listener.record_until(stop_ev, on_level=on_level)
                self._vmark("speech_end")
                trace = [{"stage": "audio_capture", "ms": int((time.perf_counter() - t_rec) * 1000), "ok": True}]
                if isinstance(streamed, np.ndarray):
                    trace.append({"stage": "stt_stream", "ms": 0, "ok": False, "reason": self._stream_error[:200]})
                if endpointer is not None and endpointer.reason:
                    trace.append({"stage": "vad_endpoint", "ms": int(endpointer.endpoint_delay_s * 1000), "ok": True,
                                  "reason": endpointer.reason})
                if self._listen_cancelled:
                    return
                self._set_listening("transcribing")
                t_asr = time.perf_counter()
                self.stt.whisper = self.listener   # Whisper — doim joriy listener (almashtirilgan bo'lsa ham)
                if force_language:
                    self._listen_result = self.stt.transcribe(audio, language)
                else:
                    self._listen_result = self.stt.transcribe(audio, None, prior=language)
                r = self._listen_result
                if r.text:
                    r.text = self._apply_uz_script(r.text, r.language)
                self._vmark("final_transcript")
                self._vstt = r.provider
                span = {"stage": "asr", "ms": int((time.perf_counter() - t_asr) * 1000), "ok": bool(r.text),
                        "provider": r.provider or getattr(self.listener, "engine", None),
                        "model": r.model or getattr(self.listener, "model_name", None)}
                if r.fallback_from:
                    span["reason"] = f"{r.fallback_from} → {r.provider}: {r.fallback_reason}"[:200]
                trace.append(span)
                if r.text and not force_language and not (r.provider or "").startswith("gemini"):
                    t_lang = time.perf_counter()
                    r.language = refine_asr_language(r.text, r.language, r.probability or None, language)
                    trace.append({"stage": "lang_detect", "ms": int((time.perf_counter() - t_lang) * 1000), "ok": True})
                self._voice_trace = trace
                if r.text:
                    self.emit({"type": "transcript", "text": r.text, "language": r.language,
                               "probability": r.probability, "supported": r.supported,
                               "stt_provider": r.provider, "stt_model": r.model, "fallback_from": r.fallback_from,
                               "fallback_reason": r.fallback_reason})
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

    _stream_error = ""
    _vstt = ""
    stt_pool = None

    def _ensure_stt_pool(self):
        if self.stt_pool is None and self.stream_available():
            from google import genai
            from google.genai import types

            from .speech.stream import LiveSTTPool, stream_config

            client = genai.Client(api_key=self.cfg.gemini_api_key, http_options=types.HttpOptions(api_version="v1beta"))
            terms = list(self.stt.vocabulary.terms)
            self.stt_pool = LiveSTTPool(client, self.cfg.gemini_stt_live_model, lambda: stream_config(terms))
        return self.stt_pool

    def stream_available(self) -> bool:
        return (self.cfg.stt_streaming and not self.cfg.offline_mode and self.cfg.stt_provider in ("auto", "gemini")
                and bool(self.cfg.gemini_api_key) and time.monotonic() >= getattr(self, "_stream_down_until", 0.0))

    def _stream_listen(self, stop_ev: threading.Event, on_level, auto: bool, language: str | None,
                       force_language: bool, mode: Mode):
        """Oqimli buyruq STT. Qaytaradi: "done" — natija qayta ishlandi; np.ndarray — oqim yiqildi, buferdagi audio
        (oddiy yo'lga beriladi); None — oqim ishlatilmaydi."""
        if not self.stream_available():
            return None
        from .lang import detect_text_language
        from .speech.stream import StreamingTranscriber

        last = [0.0]
        sent = {"text": "", "pending": ""}

        def on_partial(text: str) -> None:
            now = time.monotonic()
            if now - last[0] >= 0.08:   # ~12/s — WebSocket'ni to'ldirmaslik uchun
                last[0] = now
                sent["text"], sent["pending"] = text, ""
                self.emit({"type": "stt_partial", "text": text[:500]})
            else:
                sent["pending"] = text   # oxirgi bo'lak tashlanmaydi — oqim tugaganda yuboriladi

        factory = getattr(self, "stream_factory", None) or (lambda **kw: StreamingTranscriber(
            self.cfg.gemini_api_key, self.cfg.gemini_stt_live_model, **kw))
        from .speech.stream import MicSource

        kw = {"pool": self._ensure_stt_pool()} if getattr(self, "stream_factory", None) is None else {}
        st = factory(vocabulary=self.stt.vocabulary.terms, on_partial=on_partial, on_level=on_level, auto=auto,
                     source_factory=lambda: MicSource(self.cfg.microphone or None), **kw)
        r = st.run(stop_ev)
        if sent["pending"] and sent["pending"] != sent["text"]:
            self.emit({"type": "stt_partial", "text": sent["pending"][:500]})
        for name, key in (("stt_connected", "connected"), ("first_partial", "first_partial"),
                          ("speech_end", "speech_end"), ("final_transcript", "final")):
            if key in r.marks:
                self._vmark(name, r.marks[key])
        if r.finalized_by == "error":
            self._stream_error = r.error
            if r.error.startswith("mic:"):
                raise RuntimeError(r.error[4:].strip())   # mikrofon xatosi — oddiy yo'l ham ishlamaydi
            self._stream_down_until = time.monotonic() + 120   # takroriy muvaffaqiyatsiz ulanish yo'q
            logging.getLogger("xadicha").warning("oqimli STT ishlamadi: %s — oddiy yo'l", r.error)
            return r.audio
        if self._listen_cancelled:
            return "done"
        from .speech.recognizer import is_silence

        if r.finalized_by == "empty" and r.audio.size and not is_silence(r.audio):
            # Oqim matn bermadi, lekin audioda nutq bor (sinovda 1/12 holatda) — bufer zaxira STT'ga, buyruq yo'qolmaydi
            self._stream_error = "oqim bo'sh natija qaytardi"
            logging.getLogger("xadicha").warning("oqimli STT bo'sh natija qaytardi — buferdagi audio oddiy yo'lga")
            return r.audio
        text = self.stt.vocabulary.correct(r.text) if r.text else ""
        if force_language and language in ("uz", "ru", "en"):
            lang, prob = language, 1.0
        else:
            g = detect_text_language(text, language or "uz") if text else None
            lang, prob = (g.lang, float(g.confidence)) if g else (language or "uz", 0.0)
        t = Transcript(text, lang, prob, lang in ("uz", "ru", "en"), detected_raw="gemini-live",
                       provider="gemini-live", model=r.model)
        self._listen_result = t
        self._vstt = "gemini-live"
        text = self._apply_uz_script(text, lang)
        t.text = text
        status = "final" if r.finalized_by == "server" else "local" if r.finalized_by == "local" else r.finalized_by
        self._voice_trace = [
            {"stage": "audio_capture", "ms": r.marks.get("speech_end", r.marks.get("final", 0)), "ok": True},
            {"stage": "stt_stream", "ms": max(0, r.marks.get("final", 0) - r.marks.get("speech_end", 0)), "ok": bool(text),
             "provider": "gemini-live", "model": r.model, "reason": f"{status}:{r.reason}",
             "first_partial_ms": r.marks.get("first_partial"), "connect_ms": r.marks.get("connected")},
        ]
        self._set_listening("transcribing")
        if text:
            self.emit({"type": "transcript", "text": text, "language": lang, "probability": prob, "supported": t.supported,
                       "stt_provider": "gemini-live", "stt_model": r.model, "finalized_by": r.finalized_by,
                       "transcript_status": status, "finalize_reason": r.reason,
                       "fallback_from": "", "fallback_reason": ""})
        if auto and status == "local" and text:
            # Oraliq matn hech qachon o'zicha buyruq sifatida bajarilmaydi — foydalanuvchi tasdiqlaydi
            self.listen_handled = True
            self._vt0 = None
            analysis = understand(text, lang, None, llm_available=self.provider.name != "rules")
            analysis.needs_clarification, analysis.reason = True, "unconfirmed_transcript"
            analysis.suggestion = text
            self.emit({"type": "clarify", "text": text, "language": lang, "asr_confidence": None,
                       "analysis": analysis.public(), "transcript_status": status})
        elif auto:
            self._auto_handle(t, mode)
        else:
            self._vt0 = None
        return "done"

    # --- o'zbek yozuvi afzalligi (nutqda yozuv yo'q: STT lotinda beradi; foydalanuvchi kirillni tanlasa — o'giriladi) ---
    def _apply_uz_script(self, text: str, lang: str) -> str:
        if not text or lang != "uz" or getattr(self.cfg, "uz_script", "latin") != "cyrillic":
            return text
        from .lang import latin_to_cyrillic_uz

        return latin_to_cyrillic_uz(text, keep=self.stt.vocabulary.terms)

    def _auto_handle(self, r: Transcript, mode: Mode) -> None:
        """Avtomatik rejim: aniq buyruq — darhol bajariladi; noaniq — aniqlashtirish; bo'sh — hech narsa."""
        self.listen_handled = True
        if not r.text:
            self._vt0 = None
            self.emit({"type": "voice_result", "status": "empty"})
            return
        if not r.supported:
            self.emit({"type": "voice_result", "status": "unsupported", "language": r.language})
            return
        t_u = time.perf_counter()
        analysis = understand(r.text, r.language, r.asr_confidence, llm_available=self.provider.name != "rules")
        self._voice_trace.append({"stage": "understand", "ms": int((time.perf_counter() - t_u) * 1000), "ok": True,
                                  "clarify": analysis.needs_clarification})
        if analysis.needs_clarification:
            # Aytilgani aniq emas — o'zicha hech narsa qilinmaydi, foydalanuvchi tanlaydi
            self.emit({"type": "clarify", "text": r.text, "language": r.language,
                       "asr_confidence": r.asr_confidence, "analysis": analysis.public()})
            return
        self._vmark("intent")
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
        provider: dict[str, Any] = {"name": self.provider.name, "ok": ok, "detail": detail,
                                    "vision": self.provider.supports_vision,
                                    "grounding": bool(getattr(self.provider, "supports_grounding", False)),
                                    "search_mode": self.cfg.search_mode}
        info = getattr(self.provider, "info", None)
        if callable(info):
            provider.update(info())   # asosiy / zaxira / faol provayder, oxirgi xato (kalitsiz)
        if self.cfg.warnings:
            provider["warnings"] = list(self.cfg.warnings)
        return {
            "os": {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), platform.system()),
            "adapter": self.adapter.name,
            "provider": provider,
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
            "stt": {**self.stt.info(), "streaming": self.stream_available(),
                    "pool": self.stt_pool.info() if self.stt_pool is not None else None},
            "live": {**(self.live.info() if self.live is not None else {"active": False, "state": "idle"}),
                     "available": self.live_available()[0], "detail": self.live_available()[1],
                     "model": self.cfg.live_model},
        }
