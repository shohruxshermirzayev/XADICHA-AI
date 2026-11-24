"""Tizimning asosiy ma'lumot tuzilmalari (Pydantic).

TaskRecord — dissertatsiyadagi "tuzilmaviy vazifa rejasi": vazifa ID, buyruq,
til, niyat, harakatlar ketma-ketligi, xavf darajasi, kutilgan va haqiqiy natija,
tekshiruv mezoni, muvaffaqiyat holati.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    low = "low"            # o'qish, ilova ochish, scroll
    medium = "medium"      # matn yozish, fayl/papka yaratish, bosish
    high = "high"          # o'chirish, xabar yuborish, o'rnatish, to'lov


RISK_ORDER = {RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}


def max_risk(*levels: RiskLevel) -> RiskLevel:
    return max(levels, key=lambda r: RISK_ORDER[r])


class Mode(str, Enum):
    """Eksperimentdagi uch yondashuv."""

    voice_only = "A"   # A: faqat ovoz/matn, bitta harakat, ekransiz, tekshiruvsiz
    llm_plan = "B"     # B: LLM ko'p qadamli reja, ekransiz, tekshiruvsiz
    multimodal = "C"   # C: taklif etilgan usul — ekran konteksti + tekshiruv + tiklanish


ActionType = Literal[
    "open_app",
    "open_url",
    "click",
    "double_click",
    "type_text",
    "hotkey",
    "scroll",
    "create_folder",
    "create_file",
    "delete_path",
    "wait",
    "system",
    "web_search",    # internetdan qidirish (faqat o'qish) — text: so'rov
    "find_file",     # workspace ichida fayl nomini qidirish (faqat o'qish) — text: nom
    "reveal",        # faylni/papkani Finder'da ko'rsatish (ochmaydi, ishga tushirmaydi) — path
]

# Tizim boshqaruvi: faqat shu oldindan belgilangan, xavfsiz amallar (ixtiyoriy buyruq yo'q)
SYSTEM_CONTROLS = ("volume_up", "volume_down", "volume_set", "mute", "unmute", "brightness_up", "brightness_down")


class ToolSpec(BaseModel):
    """Qat'iy vositalar reyestri: model faqat shu harakatlarni so'ray oladi (ixtiyoriy qobiq buyrug'i yo'q)."""

    read_only: bool          # tizim holatini o'zgartirmaydi
    idempotent: bool         # xato bo'lsa xavfsiz qayta urinish mumkin (natija takrorlanmaydi)
    timeout_s: float         # adapter chaqiruvi uchun chegara
    verify: str              # tekshirish usuli


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "open_app": ToolSpec(read_only=False, idempotent=True, timeout_s=20, verify="frontmost_app"),
    "open_url": ToolSpec(read_only=False, idempotent=True, timeout_s=15, verify="command_exit_code"),
    "click": ToolSpec(read_only=False, idempotent=False, timeout_s=5, verify="visual_next_step"),
    "double_click": ToolSpec(read_only=False, idempotent=False, timeout_s=5, verify="visual_next_step"),
    "type_text": ToolSpec(read_only=False, idempotent=False, timeout_s=10, verify="visual_next_step"),
    "hotkey": ToolSpec(read_only=False, idempotent=False, timeout_s=5, verify="visual_next_step"),
    "scroll": ToolSpec(read_only=False, idempotent=True, timeout_s=5, verify="visual_next_step"),
    "create_folder": ToolSpec(read_only=False, idempotent=True, timeout_s=5, verify="path_exists"),
    "create_file": ToolSpec(read_only=False, idempotent=False, timeout_s=5, verify="path_exists"),
    "delete_path": ToolSpec(read_only=False, idempotent=False, timeout_s=15, verify="path_absent"),
    "wait": ToolSpec(read_only=True, idempotent=True, timeout_s=11, verify="none"),
    "system": ToolSpec(read_only=False, idempotent=False, timeout_s=10, verify="readback_if_possible"),
    "web_search": ToolSpec(read_only=True, idempotent=True, timeout_s=15, verify="results_nonempty"),
    "find_file": ToolSpec(read_only=True, idempotent=True, timeout_s=8, verify="results_nonempty"),
    "reveal": ToolSpec(read_only=True, idempotent=True, timeout_s=5, verify="command_exit_code"),
}


class Action(BaseModel):
    type: ActionType
    app: str | None = None
    url: str | None = None
    x: int | None = None
    y: int | None = None
    text: str | None = None
    keys: list[str] | None = None
    amount: int | None = None
    path: str | None = None
    content: str | None = None
    seconds: float | None = None
    control: str | None = None      # type="system" uchun: SYSTEM_CONTROLS dan biri; amount — qadam yoki daraja

    def describe(self) -> str:
        t = self.type
        if t == "open_app":
            return f"Ilovani ochish: {self.app}"
        if t == "open_url":
            return f"Manzilni ochish: {self.url}"
        if t in ("click", "double_click"):
            return f"{'Ikki marta bosish' if t == 'double_click' else 'Bosish'}: ({self.x}, {self.y})"
        if t == "type_text":
            return f"Matn yozish: {self.text!r}"
        if t == "hotkey":
            return f"Tugmalar: {'+'.join(self.keys or [])}"
        if t == "scroll":
            return f"Aylantirish: {self.amount}"
        if t == "create_folder":
            return f"Papka yaratish: {self.path}"
        if t == "create_file":
            return f"Fayl yaratish: {self.path}"
        if t == "delete_path":
            return f"O'CHIRISH: {self.path}"
        if t == "wait":
            return f"Kutish: {self.seconds} s"
        if t == "system":
            return f"Tizim: {self.control}" + (f" {self.amount}" if self.amount is not None else "")
        if t == "web_search":
            return f"Internetdan qidirish: {self.text}"
        if t == "find_file":
            return f"Fayl qidirish: {self.text}"
        if t == "reveal":
            return f"Finder'da ko'rsatish: {self.path}"
        return t


class Decision(BaseModel):
    """Modelning bitta qadamdagi qarori."""

    intent: str = ""
    thought: str = ""
    previous_step_ok: bool | None = None   # oldingi harakat kutilgandek bajarildimi (tekshiruv)
    action: Action | None = None
    expected_outcome: str = ""
    risk: RiskLevel = RiskLevel.low
    done: bool = False
    success: bool | None = None            # done=True bo'lganda: maqsadga erishildimi
    final_message: str = ""


class Plan(BaseModel):
    """B rejimi: bir martalik to'liq reja."""

    intent: str = ""
    steps: list[Decision] = Field(default_factory=list)
    final_message: str = ""


class StepStatus(str, Enum):
    executed = "executed"
    verified = "verified"
    failed = "failed"
    denied = "denied"
    error = "error"


class StepRecord(BaseModel):
    index: int
    action: Action
    expected_outcome: str = ""
    risk: RiskLevel = RiskLevel.low
    status: StepStatus = StepStatus.executed
    detail: str = ""
    verified: bool | None = None
    verification: str = ""          # qaysi usul bilan tekshirildi (TOOL_REGISTRY.verify)
    started_at: float = Field(default_factory=time.time)
    duration_ms: int = 0


class TaskStatus(str, Enum):
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    instruction: str
    language: str = ""
    mode: Mode = Mode.multimodal
    intent: str = ""
    planner: str = "llm"            # "rules" — tezkor yo'l (modelsiz), "llm" — model qaror qildi
    steps: list[StepRecord] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.low
    status: TaskStatus = TaskStatus.running
    final_message: str = ""
    retries: int = 0
    recoveries: int = 0
    llm_calls: int = 0
    # Kechikish taqsimoti (ms): ekran surati, model, bajarish — tezlik tahlili uchun
    timings: dict[str, int] = Field(default_factory=lambda: {"screen_ms": 0, "llm_ms": 0, "exec_ms": 0})
    started_at: float = Field(default_factory=time.time)
    finished_at: float | None = None
    # Vosita natijalari (qidiruv natijalari, topilgan fayllar) — interfeysda kartochka sifatida
    data: dict[str, Any] = Field(default_factory=dict)
    # Bosqichlar bo'yicha vaqt izi: [{stage, start, ms, ok, provider, model}] — matn/ekran tarkibisiz
    trace: list[dict[str, Any]] = Field(default_factory=list)
    resolved_from: str = ""         # havola hal qilingan bo'lsa — asl buyruq ("uni yana och")

    @property
    def latency_ms(self) -> int:
        end = self.finished_at or time.time()
        return int((end - self.started_at) * 1000)
