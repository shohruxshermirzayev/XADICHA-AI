"""Sozlamalar: backend/.env faylidan o'qiladi. Kalitlar hech qachon logga chiqarilmaydi."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "ha"}


@dataclass
class Config:
    provider: str = "mock"
    anthropic_api_key: str = field(default="", repr=False)
    claude_model: str = "claude-sonnet-5-5"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    whisper_model: str = "large-v3-turbo"
    stt_engine: str = "auto"
    tts_enabled: bool = True
    tts_engine: str = "system"
    tts_rate: int = 175
    voice_uz: str = ""
    voice_ru: str = ""
    voice_en: str = ""
    confirm_risk: str = "medium"   # shu darajadan boshlab tasdiq so'raladi: low|medium|high
    max_steps: int = 12
    fast_path: bool = True          # oddiy buyruqlar modelsiz, darhol bajariladi
    screen_max_side: int = 1024     # modelga yuboriladigan ekran rasmining eng uzun tomoni
    max_retries: int = 2
    db_path: Path = BACKEND_DIR / "data" / "xadicha.db"
    workspace: Path = Path.home()   # fayl amallari faqat shu papka ichida ruxsat etiladi

    def public(self) -> dict:
        """UI uchun xavfsiz ko'rinish (kalitsiz)."""
        return {
            "provider": self.provider,
            "model": {"claude": self.claude_model, "ollama": self.ollama_model}.get(self.provider, "qoida asosida"),
            "has_api_key": bool(self.anthropic_api_key),
            "whisper_model": self.whisper_model,
            "tts_enabled": self.tts_enabled,
            "tts_engine": self.tts_engine,
            "confirm_risk": self.confirm_risk,
            "max_steps": self.max_steps,
            "fast_path": self.fast_path,
            "workspace": str(self.workspace),
        }


def load_config() -> Config:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    provider = os.getenv("XADICHA_PROVIDER", "").strip().lower()
    if provider not in {"claude", "ollama", "mock"}:
        provider = "claude" if api_key else "ollama"
    db = os.getenv("XADICHA_DB", "").strip()
    ws = os.getenv("XADICHA_WORKSPACE", "").strip()
    return Config(
        provider=provider,
        anthropic_api_key=api_key,
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5").strip(),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").strip().rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:9b").strip(),
        whisper_model=os.getenv("WHISPER_MODEL", "large-v3-turbo").strip(),
        stt_engine=os.getenv("STT_ENGINE", "auto").strip().lower(),
        tts_enabled=_bool("TTS_ENABLED", True),
        tts_engine=os.getenv("TTS_ENGINE", "system").strip().lower(),
        tts_rate=int(os.getenv("TTS_RATE", "175")),
        voice_uz=os.getenv("VOICE_UZ", "").strip(),
        voice_ru=os.getenv("VOICE_RU", "").strip(),
        voice_en=os.getenv("VOICE_EN", "").strip(),
        confirm_risk=os.getenv("CONFIRM_RISK", "medium").strip().lower(),
        max_steps=int(os.getenv("MAX_STEPS", "12")),
        fast_path=_bool("FAST_PATH", True),
        screen_max_side=int(os.getenv("SCREEN_MAX_SIDE", "1024")),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        db_path=Path(db).expanduser() if db else BACKEND_DIR / "data" / "xadicha.db",
        workspace=Path(ws).expanduser() if ws else Path.home(),
    )
