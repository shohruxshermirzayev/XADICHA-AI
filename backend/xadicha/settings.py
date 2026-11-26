"""Ish vaqtida o'zgartiriladigan sozlamalar (maxfiy EMAS). backend/data/settings.json da saqlanadi.

API kalitlari va provayder/model tanlovi bu yerda YO'Q — ular faqat backend/.env da (qayta ishga tushirish kerak).
Brauzer localStorage'iga hech qanday maxfiy qiymat yozilmaydi.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("xadicha")


class RuntimeSettings(BaseModel):
    search_mode: Literal["auto", "always", "never"] | None = None
    stt_provider: Literal["auto", "gemini", "whisper"] | None = None
    live_enabled: bool | None = None
    tts_enabled: bool | None = None
    tts_rate: int | None = Field(default=None, ge=100, le=300)
    offline_mode: bool | None = None
    auto_language: bool | None = None          # o'chiq bo'lsa — interfeysda tanlangan til majburiy (aniqlashsiz)
    microphone: str | None = Field(default=None, max_length=200)   # "" — tizim standarti
    vocabulary: list[str] | None = None        # STT lug'ati (qo'shimcha atamalar)
    corrections: dict[str, str] | None = None  # STT tuzatishlari: "noto'g'ri" → "to'g'ri"

    model_config = {"extra": "forbid"}         # noma'lum maydon (masalan, kalit) qabul qilinmaydi

    @field_validator("vocabulary")
    @classmethod
    def _vocab(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = [t.strip()[:80] for t in v if isinstance(t, str) and t.strip()]
        return list(dict.fromkeys(out))[:500]

    @field_validator("corrections")
    @classmethod
    def _corr(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        return {k.strip()[:80]: str(val).strip()[:80] for k, val in list(v.items())[:300] if k.strip()}


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> RuntimeSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return RuntimeSettings.model_validate(data)
        except FileNotFoundError:
            return RuntimeSettings()
        except Exception as e:  # noqa: BLE001 — buzilgan fayl ishga tushishni to'xtatmasin
            log.warning("sozlamalar fayli o'qilmadi (%s): %s", self.path, e)
            return RuntimeSettings()

    def save(self, s: RuntimeSettings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(s.model_dump(exclude_none=True), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)


def input_devices() -> list[dict[str, Any]]:
    """Mikrofonlar ro'yxati (nomi va standartmi). sounddevice yo'q bo'lsa — bo'sh."""
    try:
        import sounddevice as sd

        default_in = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
        out = []
        for i, d in enumerate(sd.query_devices()):
            if int(d.get("max_input_channels", 0)) > 0:
                out.append({"name": str(d.get("name", "")), "default": i == default_in})
        return out
    except Exception:  # noqa: BLE001
        return []
