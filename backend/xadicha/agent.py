"""XADICHA AI agent yadrosi.

C rejimi (taklif etilgan usul) — har bir qadamda:
  ekranni olish → model qarori (oldingi qadamni tekshirish bilan) → xavfni baholash →
  tasdiq (kerak bo'lsa) → OS adapteri orqali bajarish → dasturiy tekshiruv →
  keyingi qadamda vizual tekshiruv → xato bo'lsa qayta urinish / qayta rejalashtirish.

B rejimi — ekransiz, bir martalik LLM rejasi, vizual tekshiruvsiz.
A rejimi — faqat buyruq matni, qoida asosida bitta harakat, tekshiruvsiz.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import safety
from .adapters.base import OSAdapter
from .config import Config
from .models import (
    Action,
    Decision,
    Mode,
    RiskLevel,
    StepRecord,
    StepStatus,
    TaskRecord,
    TaskStatus,
    max_risk,
)
from .providers.base import LLMProvider, ProviderError
from .providers.rule_based import FAST_INTENTS, RuleBasedProvider, is_simple, parse_command
from .storage import Storage
from .vision.screen import Screenshot, to_screen

log = logging.getLogger("xadicha")

# Tasdiq funksiyasi True (ruxsat) yoki rad etish sababini qaytaradi: False/"denied", "timeout", "cancelled".
ConfirmFn = Callable[[TaskRecord, Action, RiskLevel, str], "bool | str"]

DENY_USER = "foydalanuvchi rad etdi"
DENY_TIMEOUT = "tasdiq muddati tugadi — bajarilmadi"
DENY_STOPPED = "to'xtatildi"
_DENY_DETAIL = {"timeout": DENY_TIMEOUT, "cancelled": DENY_STOPPED}
EventFn = Callable[[dict[str, Any]], None]
ScreenFn = Callable[[], Screenshot]

_MSG = {
    "cancelled": {"uz": "Vazifa to'xtatildi.", "ru": "Задача остановлена.", "en": "The task was stopped."},
    "max_steps": {"uz": "Qadamlar chegarasiga yetdim, vazifa tugallanmadi.",
                  "ru": "Достигнут лимит шагов, задача не завершена.",
                  "en": "I reached the step limit; the task is not finished."},
    "too_many_failures": {"uz": "Bir necha urinishdan keyin ham bajara olmadim.",
                          "ru": "Не удалось выполнить даже после нескольких попыток.",
                          "en": "I could not complete it even after several attempts."},
    "provider": {"uz": "AI modeliga ulanib bo'lmadi.", "ru": "Не удалось подключиться к AI-модели.",
                 "en": "Could not reach the AI model."},
    "timeout": {"uz": "Tasdiq kutish muddati tugadi, harakatni bajarmadim.",
                "ru": "Время ожидания подтверждения истекло, действие не выполнено.",
                "en": "The confirmation timed out, so I did not perform the action."},
    "denied": {"uz": "Siz rad etdingiz, bu harakatni bajarmadim.", "ru": "Вы отказали, я не выполнила это действие.",
               "en": "You declined, so I did not perform this action."},
    "done": {"uz": "Bajarildi.", "ru": "Готово.", "en": "Done."},
    "internal": {"uz": "Ichki xato yuz berdi, vazifa to'xtatildi.", "ru": "Произошла внутренняя ошибка, задача остановлена.",
                 "en": "An internal error occurred; the task was stopped."},
}


def msg(key: str, lang: str) -> str:
    return _MSG[key].get(lang, _MSG[key]["en"])


class Agent:
    def __init__(self, cfg: Config, provider: LLMProvider, adapter: OSAdapter,
                 storage: Storage | None = None, confirm: ConfirmFn | None = None,
                 on_event: EventFn | None = None, screen_fn: ScreenFn | None = None):
        self.cfg = cfg
        self.provider = provider
        self.adapter = adapter
        self.storage = storage
        self.confirm = confirm or (lambda task, action, risk, why: False)
        self.on_event = on_event or (lambda e: None)
        self.screen_fn = screen_fn
        self.text_context = False   # OCR yoki accessibility mavjud bo'lsa — vision'siz model ham kontekst oladi
        self._cancel = threading.Event()

    # --- boshqaruv ---
    def stop(self) -> None:
        """Favqulodda to'xtatish."""
        self._cancel.set()

    def _emit(self, kind: str, rec: TaskRecord, **data: Any) -> None:
        self.on_event({"type": kind, "task_id": rec.id, **data})

    def _save(self, task: TaskRecord) -> None:
        if self.storage:
            self.storage.save_task(task)

    # --- asosiy kirish nuqtasi ---
    def run(self, instruction: str, language: str = "uz", mode: Mode = Mode.multimodal,
            clear_cancel: bool = True) -> TaskRecord:
        """clear_cancel=False — xizmat to'xtatish bayrog'ini vazifa navbatga qo'yilganda o'zi tozalagan;
        shunda vazifa boshlanishidan oldin bosilgan "To'xtatish" yo'qolmaydi."""
        if clear_cancel:
            self._cancel.clear()
        task = TaskRecord(instruction=instruction, language=language, mode=mode)
        self._save(task)
        self._emit("task_started", task, task=task.model_dump(mode="json"))
        try:
            if mode == Mode.voice_only:
                self._run_single(task)
            elif mode == Mode.llm_plan:
                self._run_plan(task)
            else:
                self._run_loop(task)
        except ProviderError as e:
            task.status = TaskStatus.failed
            task.final_message = msg("provider", language)
            log.warning("provayder xatosi (%s): %s", task.id, e)
            self._emit("error", task, message=str(e))
        except Exception as e:  # noqa: BLE001 — vazifa hech qachon "bajarilmoqda" holatida qolib ketmasin
            task.status = TaskStatus.failed
            task.final_message = msg("internal", language)
            log.exception("kutilmagan xato (%s)", task.id)
            self._emit("error", task, message=f"{e.__class__.__name__}: {e}")
        task.finished_at = time.time()
        task.risk = max_risk(RiskLevel.low, *[s.risk for s in task.steps]) if task.steps else RiskLevel.low
        self._save(task)
        self._emit("task_finished", task, task=task.model_dump(mode="json"))
        return task

    # --- bitta harakatni xavfsiz bajarish ---
    def _execute(self, task: TaskRecord, action: Action, proposed: RiskLevel, expected: str) -> StepRecord:
        if action.path and action.type in ("create_folder", "create_file", "delete_path"):
            # Nisbiy yo'l jarayonning joriy papkasiga emas, workspace'ga nisbatan olinadi
            p = Path(action.path.strip()).expanduser()
            if not p.is_absolute() and not safety._is_windows_path(action.path.strip()):
                action = action.model_copy(update={"path": str(self.cfg.workspace.expanduser() / p)})
        step = StepRecord(index=len(task.steps) + 1, action=action, expected_outcome=expected)
        step.risk = safety.final_risk(action, proposed, self.cfg.workspace, context=expected + " " + task.instruction)
        t0 = time.time()

        blocked = safety.blocked_reason(action, self.cfg.workspace)
        denied: str | None = None
        if blocked:
            denied = blocked
        elif self._cancel.is_set():
            denied = DENY_STOPPED
        elif safety.needs_confirmation(step.risk, self.cfg.confirm_risk):
            answer = self.confirm(task, action, step.risk, expected)
            if answer is not True:   # faqat aniq True ruxsat; satr yoki boshqa qiymat — rad
                denied = _DENY_DETAIL.get(answer, DENY_USER) if isinstance(answer, str) else DENY_USER
            elif self._cancel.is_set():
                denied = DENY_STOPPED   # tasdiqlangan, lekin shu orada to'xtatish bosildi
        if denied:
            step.status, step.detail = StepStatus.denied, denied
        elif action.type == "wait":
            # Kutish to'xtatish bilan darhol uziladi (avval 10 s gacha uxlab qolardi)
            self._emit("step_started", task, step=step.model_dump(mode="json"))
            secs = min(max(action.seconds or 1.0, 0.0), 10.0)
            if self._cancel.wait(secs):
                step.status, step.detail = StepStatus.denied, DENY_STOPPED
            else:
                step.status, step.detail = StepStatus.executed, f"{secs:g} s"
        else:
            self._emit("step_started", task, step=step.model_dump(mode="json"))
            te = time.perf_counter()
            res = self.adapter.execute(action)
            task.timings["exec_ms"] += int((time.perf_counter() - te) * 1000)
            step.detail = res.detail
            step.verified = res.verified
            if not res.ok or res.verified is False:
                step.status = StepStatus.failed
            elif res.verified:
                step.status = StepStatus.verified
            else:
                step.status = StepStatus.executed
        step.duration_ms = int((time.time() - t0) * 1000)
        task.steps.append(step)
        self._save(task)
        self._emit("step_finished", task, step=step.model_dump(mode="json"))
        return step

    def _finish_denied(self, task: TaskRecord, step: StepRecord, cancel_status: bool = True) -> None:
        """Rad etilgan qadamdan keyingi yakun: sababga mos xabar (rad / muddat / to'xtatish / siyosat)."""
        lang = task.language
        if step.detail == DENY_STOPPED:
            task.status, task.final_message = TaskStatus.cancelled, msg("cancelled", lang)
            return
        task.status = TaskStatus.cancelled if cancel_status else TaskStatus.failed
        if step.detail == DENY_USER:
            task.final_message = msg("denied", lang)
        elif step.detail == DENY_TIMEOUT:
            task.final_message = msg("timeout", lang)
        else:
            task.final_message = step.detail   # xavfsizlik siyosati sababi

    # --- A rejimi ---
    def _run_single(self, task: TaskRecord) -> None:
        rb = RuleBasedProvider()
        d = rb.decide(task.instruction, [], None, task.language)
        task.intent = d.intent
        if d.action is None:
            task.status, task.final_message = TaskStatus.failed, d.final_message
            return
        step = self._execute(task, d.action, d.risk, "")
        ok = step.status in (StepStatus.executed, StepStatus.verified)
        task.status = TaskStatus.success if ok else TaskStatus.failed
        if ok:
            task.final_message = d.final_message
        elif step.status == StepStatus.denied:
            self._finish_denied(task, step, cancel_status=False)
        else:
            task.final_message = step.detail

    # --- B rejimi ---
    def _run_plan(self, task: TaskRecord) -> None:
        tp = time.perf_counter()
        plan = self.provider.plan(task.instruction, task.language)
        task.timings["llm_ms"] += int((time.perf_counter() - tp) * 1000)
        task.llm_calls += 1
        task.intent = plan.intent
        if not plan.steps:
            task.status, task.final_message = TaskStatus.failed, plan.final_message or msg("too_many_failures", task.language)
            return
        for d in plan.steps[: self.cfg.max_steps]:
            if self._cancel.is_set():
                task.status, task.final_message = TaskStatus.cancelled, msg("cancelled", task.language)
                return
            if d.action is None:
                continue
            step = self._execute(task, d.action, d.risk, d.expected_outcome)
            if step.status == StepStatus.denied:
                self._finish_denied(task, step, cancel_status=False)
                return
            if step.status == StepStatus.failed:
                task.status, task.final_message = TaskStatus.failed, step.detail
                return
        task.status = TaskStatus.success
        task.final_message = plan.final_message or msg("done", task.language)

    # --- C rejimi (taklif etilgan usul) ---
    def _history(self, task: TaskRecord) -> list[dict[str, Any]]:
        return [{"index": s.index, "action": s.action.describe(), "status": s.status.value,
                 "detail": s.detail, "expected": s.expected_outcome} for s in task.steps]

    def _try_fast_path(self, task: TaskRecord) -> bool:
        """Oddiy buyruqni (ilova/sayt ochish, papka yaratish) modelsiz bajaradi.

        Muvaffaqiyatli bo'lsa True. Aks holda bajarilgan qadam tarixda qoladi va
        model to'liq siklda (ekran + tekshiruv) davom ettiradi.
        """
        if not self.cfg.fast_path or not is_simple(task.instruction):
            return False
        intent, actions, reply = parse_command(task.instruction, task.language)
        if intent not in FAST_INTENTS or len(actions) != 1:
            return False
        step = self._execute(task, actions[0], RiskLevel.low, "")
        if step.status in (StepStatus.verified, StepStatus.executed):
            task.intent, task.planner = intent, "rules"
            task.status, task.final_message = TaskStatus.success, reply
            return True
        if step.status == StepStatus.denied:
            self._finish_denied(task, step)
            return True
        return False   # masalan, ilova nomi noto'g'ri tanildi — model davom ettiradi

    def _run_loop(self, task: TaskRecord) -> None:
        if self._try_fast_path(task):
            return
        failures = 0
        for _ in range(self.cfg.max_steps):
            if self._cancel.is_set():
                task.status, task.final_message = TaskStatus.cancelled, msg("cancelled", task.language)
                return

            t0 = time.perf_counter()
            # Ekran surati: vision model uchun rasm, OCR/accessibility bo'lsa — matnli kontekst ham
            want_shot = self.screen_fn and (self.provider.supports_vision or self.text_context)
            shot = self.screen_fn() if want_shot else None
            screen = shot if (shot is not None and self.provider.supports_vision) else None
            t1 = time.perf_counter()
            extra = {"context": shot.context} if (shot is not None and shot.context) else {}
            decision: Decision = self.provider.decide(task.instruction, self._history(task), screen, task.language,
                                                      **extra)
            t2 = time.perf_counter()
            if shot is not None and decision.action is not None and decision.action.x is not None \
                    and decision.action.y is not None:
                # Model rasm koordinatasini qaytaradi; bosish mantiqiy ekran nuqtasida bo'ladi (Retina/masshtab)
                sx, sy = to_screen(decision.action.x, decision.action.y, shot)
                decision.action = decision.action.model_copy(update={"x": sx, "y": sy})
            task.timings["screen_ms"] += int((t1 - t0) * 1000)
            task.timings["llm_ms"] += int((t2 - t1) * 1000)
            task.llm_calls += 1
            if decision.intent and not task.intent:
                task.intent = decision.intent

            # Vizual tekshiruv: model oldingi qadam natijasini ekranda baholaydi
            if task.steps and decision.previous_step_ok is not None:
                last = task.steps[-1]
                if last.status == StepStatus.executed:
                    last.verified = decision.previous_step_ok
                    last.status = StepStatus.verified if decision.previous_step_ok else StepStatus.failed
                    self._save(task)
                    self._emit("step_verified", task, step=last.model_dump(mode="json"))
                    if last.status == StepStatus.failed:
                        failures += 1
                if last.status == StepStatus.verified:
                    failures = 0
                elif last.status == StepStatus.failed and decision.action is not None:
                    task.recoveries += 1   # xatodan keyin yangi urinish (tiklanish)

            if failures > self.cfg.max_retries:
                task.status, task.final_message = TaskStatus.failed, msg("too_many_failures", task.language)
                return

            if decision.done or decision.action is None:
                unresolved = bool(task.steps) and task.steps[-1].status in (StepStatus.failed, StepStatus.denied)
                success = decision.success if decision.success is not None else not unresolved
                task.status = TaskStatus.success if success else TaskStatus.failed
                task.final_message = decision.final_message or msg("done", task.language)
                return

            step = self._execute(task, decision.action, decision.risk, decision.expected_outcome)
            if step.status == StepStatus.failed:
                failures += 1
                task.retries += 1
                if failures > self.cfg.max_retries:
                    task.status, task.final_message = TaskStatus.failed, msg("too_many_failures", task.language)
                    return
            if step.status == StepStatus.denied:
                # Foydalanuvchi rad etgan yoki siyosat taqiqlagan harakatdan keyin vazifa to'xtatiladi
                self._finish_denied(task, step)
                return

        task.status, task.final_message = TaskStatus.failed, msg("max_steps", task.language)
