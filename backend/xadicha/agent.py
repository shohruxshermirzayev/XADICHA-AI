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
from .adapters.base import ExecResult, OSAdapter
from .config import Config
from .models import (
    TOOL_REGISTRY,
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
from .providers.rule_based import RuleBasedProvider, parse_command
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
    "no_results": {"uz": "Hech narsa topilmadi.", "ru": "Ничего не найдено.", "en": "Nothing was found."},
    "search_failed": {"uz": "Qidiruv ishlamadi (internet yoki qidiruv xizmati javob bermadi).",
                      "ru": "Поиск не удался (нет интернета или сервис не ответил).",
                      "en": "The search failed (no internet or the search service did not respond)."},
    "found_results": {"uz": "Topilgan natijalar:", "ru": "Найденные результаты:", "en": "Results found:"},
    "files_found": {"uz": "{n} ta topildi:", "ru": "Найдено {n}:", "en": "Found {n}:"},
    "no_repeat": {"uz": "Muvaffaqiyatsiz bo'lgan bu harakat takrorlanmaydi — boshqa usul kerak.",
                  "ru": "Это неудавшееся действие не повторяется — нужен другой способ.",
                  "en": "This failed action is not repeated blindly — a different approach is needed."},
    "internal": {"uz": "Ichki xato yuz berdi, vazifa to'xtatildi.", "ru": "Произошла внутренняя ошибка, задача остановлена.",
                 "en": "An internal error occurred; the task was stopped."},
}


# Model ulanmagan yoki javob bermasa — suhbat uchun tayyor javoblar (hech narsa to'qilmaydi)
_CHAT_FALLBACK = {
    "greeting": {"uz": "Salom! Men XADICHA. Buyruq bering yoki savolingizni ayting.",
                 "ru": "Привет! Я XADICHA. Дайте команду или задайте вопрос.",
                 "en": "Hi! I'm XADICHA. Give me a command or ask a question."},
    "thanks": {"uz": "Arzimaydi! Yana nima yordam kerak?", "ru": "Не за что! Чем ещё помочь?",
               "en": "You're welcome! What else can I do for you?"},
    "identity": {"uz": "Men XADICHA — kompyuteringizni ovoz va matn bilan boshqaradigan yordamchiman. Ilova va saytlarni "
                       "ochaman, internetda qidiraman, fayllarni topaman, ovoz va yorug'likni o'zgartiraman.",
                 "ru": "Я XADICHA — помощник, который управляет компьютером голосом и текстом. Открываю приложения и сайты, "
                       "ищу в интернете, нахожу файлы, меняю громкость и яркость.",
                 "en": "I'm XADICHA, an assistant that controls your computer by voice and text. I open apps and websites, "
                       "search the web, find files and change volume and brightness."},
    "other": {"uz": "Hozir suhbat uchun model ulanmagan. Buyruq bering, masalan: Safari ni och.",
              "ru": "Сейчас модель для разговора не подключена. Дайте команду, например: Открой Safari.",
              "en": "No model is connected for conversation right now. Give a command, for example: Open Safari."},
}


def chat_fallback(text: str, lang: str) -> str:
    import re as _re

    low = text.lower()
    if _re.search(r"rahmat|raxmat|tashakkur|раҳмат|рахмат|спасибо|благодар|thank", low):
        kind = "thanks"
    elif _re.search(r"kimsan|kimsiz|isming|qila olas|кимсан|кто ты|как тебя зовут|что ты умеешь|who are you|your name|what can you do", low):
        kind = "identity"
    elif _re.search(r"salom|assalom|xayrli|hayrli|салом|ассалом|привет|здравств|добр|hello|\bhi\b|hey|good morning|good evening", low):
        kind = "greeting"
    else:
        kind = "other"
    return _CHAT_FALLBACK[kind].get(lang, _CHAT_FALLBACK[kind]["en"])


def clean_spoken(text: str, limit: int = 700) -> str:
    """Ovozda o'qiladigan matn: markdown belgilari olib tashlanadi, haddan uzun javob kesiladi."""
    import re as _re

    t = _re.sub(r"[*_#`>]+", "", text)
    t = _re.sub(r"\[(\d+)\]", "", t)
    t = _re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        cut = t[:limit]
        t = cut[: max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? ")) + 1] or cut
    return t


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
        self.conversation = None          # Conversation — suhbat konteksti (service beradi)
        self.search_fn = None             # web_search(query, lang) — sinovda almashtiriladi
        self.file_fn = None               # find_files(query, root)
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
                ws = self.cfg.workspace.expanduser()
                # workspace butun uy papkasi bo'lsa — joy aytilmagan papka/fayl Desktop'da yaratiladi
                # (uy papkasining ildizini to'ldirmaslik uchun, avvalgi xatti-harakat); aks holda workspace ichida
                base = ws / "Desktop" if ws.resolve() == Path.home().resolve() and (ws / "Desktop").is_dir() else ws
                action = action.model_copy(update={"path": str(base / p)})
        step = StepRecord(index=len(task.steps) + 1, action=action, expected_outcome=expected)
        spec = TOOL_REGISTRY.get(action.type)
        step.verification = spec.verify if spec else ""
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
        elif action.type in ("web_search", "find_file"):
            self._emit("step_started", task, step=step.model_dump(mode="json"))
            te = time.perf_counter()
            res = self._run_tool(task, action)
            task.timings["exec_ms"] += int((time.perf_counter() - te) * 1000)
            step.detail, step.verified = res.detail, res.verified
            step.status = StepStatus.verified if res.ok and res.verified else StepStatus.failed
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
            res = self._call_adapter(action)
            task.timings["exec_ms"] += int((time.perf_counter() - te) * 1000)
            self._span(task, f"exec:{action.type}", te, res.ok)
            if res.verify_ms is not None:
                task.trace.append({"stage": "verify", "ms": int(res.verify_ms), "ok": res.verified is not False,
                                   "action": action.type})
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

    # --- vaqt izi ---
    @staticmethod
    def _span(task: TaskRecord, stage: str, t0_perf: float, ok: bool = True, **meta: Any) -> None:
        """Bosqich vaqti (matn yoki ekran tarkibisiz)."""
        task.trace.append({"stage": stage, "ms": int((time.perf_counter() - t0_perf) * 1000), "ok": bool(ok),
                           **{k: v for k, v in meta.items() if v is not None}})

    # --- adapter chaqiruvi: vaqt chegarasi bilan ---
    def _call_adapter(self, action: Action) -> ExecResult:
        spec = TOOL_REGISTRY.get(action.type)
        timeout = spec.timeout_s if spec else 15.0
        box: dict[str, ExecResult] = {}

        def work() -> None:
            box["r"] = self.adapter.execute(action)

        th = threading.Thread(target=work, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            # Ipni majburan to'xtatib bo'lmaydi; natija kutilmaydi va qadam muvaffaqiyatsiz deb belgilanadi
            return ExecResult(False, f"vaqt tugadi ({timeout:g} s)", verified=False)
        return box.get("r") or ExecResult(False, "natija yo'q", verified=False)

    # --- vositalar: internet va fayl qidiruvi (faqat o'qish) ---
    def _run_tool(self, task: TaskRecord, action: Action) -> ExecResult:
        q = (action.text or "").strip()
        lang = task.language
        if action.type == "web_search":
            from .tools.search import web_search

            fn = self.search_fn or web_search
            t0 = time.perf_counter()
            results, provider, errors = fn(q, lang)
            self._span(task, "tool:web_search", t0, bool(results), provider=provider or None)
            task.data["query"] = q
            task.data["results"] = [r.public() if hasattr(r, "public") else dict(r) for r in results]
            task.data["search_provider"] = provider
            if not results:
                task.data["errors"] = errors
                only_empty = errors and all(e.endswith(":empty") for e in errors)
                return ExecResult(False, msg("no_results" if only_empty else "search_failed", lang), verified=False)
            return ExecResult(True, f"{len(results)} natija ({provider})", verified=True)
        from .tools.files import find_files

        fn = self.file_fn or find_files
        t0 = time.perf_counter()
        paths = fn(q, self.cfg.workspace)
        self._span(task, "tool:find_file", t0, bool(paths))
        task.data["query"] = q
        task.data["results"] = [{"title": Path(p).name, "path": str(p)} for p in paths]
        if not paths:
            return ExecResult(False, msg("no_results", lang), verified=False)
        return ExecResult(True, f"{len(paths)} ta", verified=True)

    def _summarize_search(self, task: TaskRecord) -> str:
        """Natijalar asosida qisqa javob. Model faqat berilgan natijalardan foydalanadi; bo'lmasa — ro'yxat."""
        results = task.data.get("results") or []
        lang = task.language
        listing = " ".join(f"{i}) {r.get('title', '')}" for i, r in enumerate(results[:3], 1))
        fallback = f"{msg('found_results', lang)} {listing}"
        if isinstance(self.provider, RuleBasedProvider):
            return fallback
        numbered = "\n".join(f"[{i}] {r.get('title', '')} — {r.get('snippet', '')} ({r.get('url', '')})"
                              for i, r in enumerate(results[:5], 1))
        names = {"uz": "Uzbek", "ru": "Russian", "en": "English"}
        system = ("You answer the user's question using ONLY the numbered web search results below. "
                  f"Reply with ONE JSON object {{\"answer\": \"...\"}} written in {names.get(lang, 'English')}, "
                  "2-4 short sentences, cite sources like [1]. If the results do not contain the answer, say so. "
                  "Never invent facts that are not in the results.")
        t0 = time.perf_counter()
        try:
            raw = self.provider.complete(system, f"Question: {task.data.get('query', '')}\n\nResults:\n{numbered}", None)
            task.llm_calls += 1
            from .providers.prompts import parse_json

            answer = str(parse_json(raw).get("answer", "")).strip()
            self._span(task, "llm:summarize", t0, bool(answer), provider=self.provider.name)
            return answer or fallback
        except Exception:  # noqa: BLE001 — model ishlamasa ham natijalar ko'rsatiladi
            self._span(task, "llm:summarize", t0, False, provider=self.provider.name)
            return fallback
        finally:
            task.timings["llm_ms"] += int((time.perf_counter() - t0) * 1000)

    def _run_chat(self, task: TaskRecord) -> None:
        """Oddiy suhbat: ekran surati yo'q, hech qanday harakat yo'q — faqat javob matni (bitta model chaqiruvi)."""
        import datetime as _dt

        from .providers.base import os_name
        from .providers.prompts import CHAT_PROMPT, parse_json

        task.intent, task.planner = "chat", "chat"
        lang = task.language
        task.status = TaskStatus.success
        if isinstance(self.provider, RuleBasedProvider):
            task.final_message = chat_fallback(task.instruction, lang)
            return
        names = {"uz": "Uzbek", "ru": "Russian", "en": "English"}
        system = CHAT_PROMPT.format(
            os_name=os_name(),
            language=names.get(lang, "English"),
            now=_dt.datetime.now().strftime("%Y-%m-%d %H:%M, %A"),
            conversation=(self.conversation.summary() if self.conversation is not None else "") or "(empty)",
        )
        t0 = time.perf_counter()
        reply = ""
        try:
            raw = self.provider.complete(system, f"User: {task.instruction}", None)
            task.llm_calls += 1
            data = parse_json(raw)
            reply = clean_spoken(str(data.get("reply") or data.get("final_message") or data.get("answer") or ""))
        except Exception:  # noqa: BLE001 — model ishlamasa tayyor javob
            reply = ""
        self._span(task, "llm:chat", t0, bool(reply), provider=self.provider.name, model=getattr(self.provider, "model", None))
        task.timings["llm_ms"] += int((time.perf_counter() - t0) * 1000)
        task.final_message = reply or chat_fallback(task.instruction, lang)

    def _blind_repeat(self, task: TaskRecord, action: Action) -> bool:
        """Oxirgi qadam muvaffaqiyatsiz bo'lsa va model aynan shu takrorlab bo'lmaydigan harakatni yana so'rasa."""
        if not task.steps:
            return False
        last = task.steps[-1]
        spec = TOOL_REGISTRY.get(action.type)
        return (last.status == StepStatus.failed and spec is not None and not spec.idempotent
                and last.action.model_dump(exclude_none=True) == action.model_dump(exclude_none=True))

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
        intent, actions, reply = parse_command(task.instruction, task.language)
        if intent == "system" and actions:
            self._run_system(task, actions, reply)
            return
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
        self._span(task, "llm:plan", tp, bool(plan.steps), provider=self.provider.name,
                   model=getattr(self.provider, "model", None))
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

    def _run_system(self, task: TaskRecord, actions: list[Action], reply: str) -> bool:
        task.intent, task.planner = "system", "rules"
        for a in actions:
            step = self._execute(task, a, RiskLevel.low, "")
            if step.status == StepStatus.denied:
                self._finish_denied(task, step)
                return True
            if step.status == StepStatus.failed:
                task.status, task.final_message = TaskStatus.failed, step.detail
                return True
        task.status, task.final_message = TaskStatus.success, reply
        return True

    def _run_routed(self, task: TaskRecord) -> str | None:
        """Marshrut bo'yicha bajarish. Qaytaradi: None — tugadi; matn — modelga beriladigan buyruq (autonomous)."""
        from .router import route

        t0 = time.perf_counter()
        r = route(task.instruction, task.language, self.conversation, fast_path=self.cfg.fast_path)
        self._span(task, "route", t0, True, path=r.path)
        if r.resolved_from:
            task.resolved_from = r.resolved_from
        if r.path == "clarify":
            task.intent, task.planner = r.intent, "rules"
            task.status, task.final_message = TaskStatus.failed, r.reply
            return None
        if r.path == "autonomous":
            return r.note or task.instruction
        if r.path == "chat":
            self._run_chat(task)
            return None
        task.intent, task.planner = r.intent or task.intent, "rules" if r.path == "fast" else "tool"
        if r.intent == "system":
            self._run_system(task, r.actions, r.reply)
            return None
        for a in r.actions:
            step = self._execute(task, a, RiskLevel.low, "")
            if step.status == StepStatus.denied:
                self._finish_denied(task, step)
                return None
            if step.status == StepStatus.failed:
                if r.path == "fast" and a.type == "open_app":
                    task.planner = "llm"      # masalan, ilova nomi noto'g'ri tanildi — model davom ettiradi
                    return task.instruction
                task.status, task.final_message = TaskStatus.failed, step.detail
                return None
        task.status = TaskStatus.success
        if r.intent == "web_search" and task.data.get("results"):
            task.final_message = self._summarize_search(task)
        elif r.intent == "find_file" and task.data.get("results"):
            names = ", ".join(x["title"] for x in task.data["results"][:5])
            task.final_message = f"{msg('files_found', task.language).format(n=len(task.data['results']))} {names}"
        else:
            task.final_message = r.reply or msg("done", task.language)
        return None

    def _run_loop(self, task: TaskRecord) -> None:
        instruction = self._run_routed(task)
        if instruction is None:
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
            extra: dict[str, Any] = {"context": shot.context} if (shot is not None and shot.context) else {}
            conv = self.conversation.summary() if self.conversation is not None else ""
            if conv:
                extra["conversation"] = conv
            if shot is not None:
                self._span(task, "screen", t0, True)
                for k, v in (getattr(shot, "timings", None) or {}).items():
                    task.trace.append({"stage": f"screen:{k}", "ms": int(v), "ok": True})
            decision: Decision = self.provider.decide(instruction, self._history(task), screen, task.language,
                                                      **extra)
            t2 = time.perf_counter()
            self._span(task, "llm:decide", t1, True, provider=self.provider.name,
                       model=getattr(self.provider, "model", None))
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

            if self._blind_repeat(task, decision.action):
                # Takrorlab bo'lmaydigan muvaffaqiyatsiz harakatni ko'r-ko'rona qayta bajarmaymiz
                step = StepRecord(index=len(task.steps) + 1, action=decision.action, status=StepStatus.failed,
                                  detail=msg("no_repeat", task.language), expected_outcome=decision.expected_outcome)
                task.steps.append(step)
                self._emit("step_finished", task, step=step.model_dump(mode="json"))
                failures += 1
                if failures > self.cfg.max_retries:
                    task.status, task.final_message = TaskStatus.failed, msg("too_many_failures", task.language)
                    return
                continue
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
