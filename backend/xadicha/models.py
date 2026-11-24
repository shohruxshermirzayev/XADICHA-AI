"""Tizimning asosiy ma'lumot tuzilmalari (Pydantic).

TaskRecord — dissertatsiyadagi "tuzilmaviy vazifa rejasi": vazifa ID, buyruq,
til, niyat, harakatlar ketma-ketligi, xavf darajasi, kutilgan va haqiqiy natija,
tekshiruv mezoni, muvaffaqiyat holati.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Literal

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
]

# Tizim boshqaruvi: faqat shu oldindan belgilangan, xavfsiz amallar (ixtiyoriy buyruq yo'q)
SYSTEM_CONTROLS = ("volume_up", "volume_down", "volume_set", "mute", "unmute", "brightness_up", "brightness_down")


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

    @property
    def latency_ms(self) -> int:
        end = self.finished_at or time.time()
        return int((end - self.started_at) * 1000)
