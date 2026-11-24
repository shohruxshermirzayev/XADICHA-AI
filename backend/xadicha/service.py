"""Ilova xizmati: agent, nutq, tasdiqlar va hodisalarni bir joyda boshqaradi (API va CLI uchun)."""

from __future__ import annotations

import logging
import platform
import threading
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
    def __init__(self, task_id: str, action: Action, risk: RiskLevel, reason: str):
        self.task_id, self.action, self.risk, self.reason = task_id, action, risk, reason
        self.event = threading.Event()
        self.approved = False

    def public(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "action": self.action.model_dump(), "description": self.action.describe(),
                "risk": self.risk.value, "reason": self.reason}


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
        self._listen_stop: threading.Event | None = None
        self._listen_thread: threading.Thread | None = None
        self._listen_result: Transcript | None = None

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
    def _confirm(self, task: TaskRecord, action: Action, risk: RiskLevel, reason: str) -> bool:
        p = PendingConfirmation(task.id, action, risk, reason)
        self.pending = p
        self.emit({"type": "confirm_request", **p.public()})
        answered = p.event.wait(self.confirm_timeout)
        self.pending = None
        self.emit({"type": "confirm_resolved", "task_id": task.id, "approved": answered and p.approved})
        return answered and p.approved

    def answer_confirmation(self, task_id: str, approve: bool) -> bool:
        p = self.pending
        if p is None or p.task_id != task_id:
            return False
        p.approved = approve
        p.event.set()
        return True

    # --- vazifalar ---
    @property
    def busy(self) -> bool:
        return self.current_task is not None

    def run_task(self, instruction: str, language: str = "uz", mode: Mode = Mode.multimodal,
                 speak: bool = True) -> TaskRecord:
        if not self._run_lock.acquire(blocking=False):
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
        if self.busy:
            raise RuntimeError("Boshqa vazifa bajarilmoqda.")
        threading.Thread(target=self._safe_run, args=(instruction, language, mode), daemon=True).start()

    def _safe_run(self, instruction: str, language: str, mode: Mode) -> None:
        try:
            self.run_task(instruction, language, mode)
        except Exception as e:  # noqa: BLE001
            self.emit({"type": "error", "message": f"{e.__class__.__name__}: {e}"})

    def stop(self) -> None:
        self.agent.stop()
        self.speaker.stop()
        if self.pending:
            self.answer_confirmation(self.pending.task_id, False)
        self.emit({"type": "stopped"})

    # --- tinglash ---
    def start_listening(self, language: str | None = None) -> None:
        if self._listen_thread and self._listen_thread.is_alive():
            return
        self.speaker.stop()
        self._listen_stop = threading.Event()
        self._listen_result = None

        def work() -> None:
            try:
                audio = self.listener.record_until(self._listen_stop)  # type: ignore[arg-type]
                self.emit({"type": "listening", "state": "transcribing"})
                self._listen_result = self.listener.transcribe(audio, language)
                r = self._listen_result
                self.emit({"type": "transcript", "text": r.text, "language": r.language,
                           "probability": r.probability, "supported": r.supported})
            except Exception as e:  # noqa: BLE001 — mikrofon ruxsati yo'q va h.k.
                self.emit({"type": "error", "message": f"Mikrofon: {e}"})
            finally:
                self.emit({"type": "listening", "state": "idle"})

        self._listen_thread = threading.Thread(target=work, daemon=True)
        self._listen_thread.start()
        self.emit({"type": "listening", "state": "recording"})

    def stop_listening(self, timeout: float = 120) -> Transcript | None:
        if self._listen_stop:
            self._listen_stop.set()
        if self._listen_thread:
            self._listen_thread.join(timeout)
        return self._listen_result

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
            "permissions": self.adapter.permissions(),
            "tts": {lang: self.speaker.available(lang) for lang in ("uz", "ru", "en")},
            "stt_engine": self.listener.engine,
        }
