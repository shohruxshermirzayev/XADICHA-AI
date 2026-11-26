"""Sozlamalar: backend/.env faylidan o'qiladi. Kalitlar hech qachon logga chiqarilmaydi."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .redaction import register_secret

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

PROVIDERS = {"gemini", "claude", "ollama", "mock"}
SEARCH_MODES = {"auto", "always", "never"}
# Standart model — rasmiy ro'yxatda "Stable" (ai.google.dev/gemini-api/docs/models, 2026-11). Eskirsa — GEMINI_MODEL bilan
# almashtiriladi; health() modelning API'da mavjudligini tekshiradi va topilmasa aniq xabar beradi.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
# Asosiy model yiqilsa (5xx/timeout/404) — Ollama'dan oldin sinaladigan Gemini modellari (rasmiy "Stable" ro'yxatidan)
DEFAULT_GEMINI_FALLBACK_MODELS = "gemini-3.5-flash-lite"
# Nutqni aniqlash (Interactions API) va real vaqt ovozli suhbat (Live API) — rasmiy hujjatlar, 2026-11
DEFAULT_GEMINI_STT_MODEL = "gemini-3.5-transcribe"
DEFAULT_GEMINI_LIVE_MODEL = "gemini-3.8-live"
DEFAULT_GEMINI_STT_LIVE_MODEL = "gemini-3.5-transcribe-live"   # oqimli (interim + final) buyruq STT
STT_MODES = {"auto", "gemini", "whisper"}

# Kalitlar bir marta o'qiladi va jarayon muhitidan olib tashlanadi: `open`, `osascript`, `say` kabi
# tashqi dasturlar ularni meros qilib olmaydi. Qayta load_config() chaqirilsa — xotiradagi qiymat ishlatiladi.
_SECRETS: dict[str, str] = {}


def _secret(name: str) -> str:
    if name in os.environ:
        _SECRETS[name] = os.environ.pop(name).strip()
    value = _SECRETS.get(name, "")
    register_secret(value)
    return value


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
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_fallback_models: list[str] = field(default_factory=lambda: DEFAULT_GEMINI_FALLBACK_MODELS.split(","))
    gemini_thinking: str = "low"     # low | medium | high | "" (model standarti)
    gemini_timeout_s: float = 20.0
    search_mode: str = "auto"        # auto | always | never — Google Search grounding (faqat Gemini)
    fallback: str = "ollama"         # Gemini ishlamasa: ollama | none
    stt_provider: str = "auto"       # auto | gemini | whisper
    gemini_stt_model: str = DEFAULT_GEMINI_STT_MODEL
    vocabulary_file: str = ""        # maxsus lug'at + tuzatishlar (JSON)
    stt_streaming: bool = True       # buyruq rejimida oqimli STT (Gemini Live Transcription), ishlamasa — oddiy yo'l
    gemini_stt_live_model: str = DEFAULT_GEMINI_STT_LIVE_MODEL
    live_enabled: bool = True        # Gemini Live (real vaqt ovozli suhbat) — kalit bo'lsa
    live_model: str = DEFAULT_GEMINI_LIVE_MODEL
    live_voice: str = ""             # Live ovozi (bo'sh — model standarti)
    offline_mode: bool = False       # bulut xizmatlari (Gemini, Google Search, Live) ishlatilmaydi
    auto_language: bool = True       # nutq tilini avtomatik aniqlash (o'chiq — tanlangan til majburiy)
    microphone: str = ""             # kirish qurilmasi nomi ("" — tizim standarti)
    warnings: list[str] = field(default_factory=list)   # sozlama xatolari (statusda ko'rinadi)
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
            "model": {"claude": self.claude_model, "ollama": self.ollama_model,
                      "gemini": self.gemini_model}.get(self.provider, "qoida asosida"),
            "has_api_key": bool(self.gemini_api_key if self.provider == "gemini" else self.anthropic_api_key),
            "search_mode": self.search_mode,
            "fallback": self.fallback if self.provider == "gemini" else "none",
            "fallback_model": self.ollama_model if self.provider == "gemini" and self.fallback == "ollama" else "",
            "gemini_models": [self.gemini_model, *self.gemini_fallback_models] if self.provider == "gemini" else [],
            "stt_provider": self.stt_provider,
            "gemini_stt_model": self.gemini_stt_model,
            "stt_streaming": self.stt_streaming,
            "gemini_stt_live_model": self.gemini_stt_live_model,
            "live_enabled": self.live_enabled,
            "live_model": self.live_model,
            "offline_mode": self.offline_mode,
            "auto_language": self.auto_language,
            "whisper_model": self.whisper_model,
            "tts_enabled": self.tts_enabled,
            "tts_engine": self.tts_engine,
            "confirm_risk": self.confirm_risk,
            "max_steps": self.max_steps,
            "fast_path": self.fast_path,
            "workspace": str(self.workspace),
        }


def load_config() -> Config:
    api_key = _secret("ANTHROPIC_API_KEY")
    gemini_key = _secret("GEMINI_API_KEY")
    warnings: list[str] = []
    raw_provider = os.getenv("XADICHA_PROVIDER", "").strip().lower()
    provider = raw_provider
    if provider not in PROVIDERS:
        provider = "gemini" if gemini_key else "claude" if api_key else "ollama"
        if raw_provider:   # jimgina almashtirilmaydi — sabab statusda ko'rinadi
            warnings.append(f"XADICHA_PROVIDER={raw_provider!r} noma'lum (mumkin: {', '.join(sorted(PROVIDERS))}); "
                            f"{provider} ishlatilmoqda")
    search_mode = os.getenv("XADICHA_SEARCH_MODE", "auto").strip().lower() or "auto"
    if search_mode not in SEARCH_MODES:
        warnings.append(f"XADICHA_SEARCH_MODE={search_mode!r} noma'lum (mumkin: auto, always, never); auto ishlatilmoqda")
        search_mode = "auto"
    stt = os.getenv("XADICHA_STT", "auto").strip().lower() or "auto"
    if stt not in STT_MODES:
        warnings.append(f"XADICHA_STT={stt!r} noma'lum (mumkin: auto, gemini, whisper); auto ishlatilmoqda")
        stt = "auto"
    vocab = os.getenv("XADICHA_VOCABULARY", "").strip()
    if not vocab and (BACKEND_DIR / "vocabulary.json").exists():
        vocab = str(BACKEND_DIR / "vocabulary.json")
    fallback = os.getenv("XADICHA_FALLBACK", "ollama").strip().lower() or "ollama"
    if fallback not in {"ollama", "none"}:
        warnings.append(f"XADICHA_FALLBACK={fallback!r} noma'lum (mumkin: ollama, none); ollama ishlatilmoqda")
        fallback = "ollama"
    db = os.getenv("XADICHA_DB", "").strip()
    ws = os.getenv("XADICHA_WORKSPACE", "").strip()
    return Config(
        provider=provider,
        anthropic_api_key=api_key,
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5").strip(),
        gemini_api_key=gemini_key,
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
        gemini_fallback_models=[m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", DEFAULT_GEMINI_FALLBACK_MODELS)
                                .split(",") if m.strip()],
        gemini_thinking=os.getenv("GEMINI_THINKING", "low").strip().lower(),
        gemini_timeout_s=float(os.getenv("GEMINI_TIMEOUT", "20") or 20),
        search_mode=search_mode,
        fallback=fallback,
        stt_provider=stt,
        gemini_stt_model=os.getenv("GEMINI_STT_MODEL", "").strip() or DEFAULT_GEMINI_STT_MODEL,
        stt_streaming=_bool("XADICHA_STT_STREAMING", True),
        gemini_stt_live_model=os.getenv("GEMINI_STT_LIVE_MODEL", "").strip() or DEFAULT_GEMINI_STT_LIVE_MODEL,
        vocabulary_file=str(Path(vocab).expanduser()) if vocab else "",
        live_enabled=_bool("GEMINI_LIVE", True),
        live_model=os.getenv("GEMINI_LIVE_MODEL", "").strip() or DEFAULT_GEMINI_LIVE_MODEL,
        live_voice=os.getenv("GEMINI_LIVE_VOICE", "").strip(),
        warnings=warnings,
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
