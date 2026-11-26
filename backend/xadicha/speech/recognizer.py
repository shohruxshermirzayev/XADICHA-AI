"""Provayderdan mustaqil nutqni aniqlash (STT): Gemini Transcribe va lokal Whisper.

Rejimlar (XADICHA_STT):
  auto    — Gemini Transcribe (kalit bor va ishlayotgan bo'lsa), aks holda Whisper
  gemini  — Gemini Transcribe; ishlamasa Whisper (zaxira) — almashinuv metadata'da yoziladi, jimgina emas
  whisper — faqat lokal Whisper (internetsiz)

Har bir natijada haqiqatan ishlagan provayder (`provider`, `model`) va zaxiraga o'tish sababi (`fallback_from`,
`fallback_reason`) saqlanadi. Jimlik yoki juda qisqa audio tarmoqqa yuborilmaydi; Gemini xato bersa, keyingi
so'rovlar ma'lum vaqt Whisper'da bajariladi (cheksiz qayta urinish yo'q).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..redaction import redact
from .stt import SAMPLE_RATE, SUPPORTED, Transcript

log = logging.getLogger("xadicha")

STT_MODES = {"auto", "gemini", "whisper"}
BCP47 = {"uz": "uz-UZ", "ru": "ru-RU", "en": "en-US"}
_COOLDOWN = {"auth": 600.0, "config": 600.0, "quota": 120.0, "server": 60.0, "network": 30.0, "timeout": 30.0}
MIN_SPEECH_RMS = 0.004     # bundan past — amalda jimlik (tarmoqqa yuborilmaydi)

# Standart lug'at: ilova nomlari, texnik atamalar va o'zbekcha buyruq so'zlari (foydalanuvchi faylida kengaytiriladi)
DEFAULT_TERMS = [
    "Xadicha", "XADICHA AI", "Gemini", "Gemini Live", "Claude", "Ollama", "Terminal", "Next.js", "Safari", "Google Chrome", "Telegram", "Notes", "Finder", "VS Code", "Visual Studio Code", "Excel",
    "Word", "PowerPoint", "PDF", "YouTube", "Gmail", "GitHub", "Python", "Spotify", "WhatsApp", "Zoom",
    "Gemini", "Wi-Fi", "Bluetooth", "Downloads", "Desktop", "och", "yop", "qidir", "top", "papka", "fayl",
]


_UZ_APOS = re.compile(r"[ʻʼ’‘`´]")


def normalize_uz(text: str) -> str:
    """O'zbekcha apostrof va harflar: ʻ ’ ‘ ` ´ → ' ; "o '" / "g '" bo'sh joylari yopiladi (o' g' — bitta harf)."""
    t = _UZ_APOS.sub("'", text)
    t = re.sub(r"\b([OoGg])\s+'(?=\w)", r"\1'", t)
    return t


def installed_app_names(limit: int = 200) -> list[str]:
    """Mac'dagi ilovalar nomlari (STT lug'ati uchun; faqat nomlar, hech narsa ochilmaydi)."""
    from pathlib import Path as _P

    names: list[str] = []
    for d in (_P("/Applications"), _P("/System/Applications"), _P.home() / "Applications"):
        try:
            names += [p.stem for p in d.glob("*.app")]
        except OSError:
            continue
    return list(dict.fromkeys(n for n in names if 2 <= len(n) <= 40))[:limit]


def recent_file_names(limit: int = 50) -> list[str]:
    """Desktop / Downloads / Documents dagi eng yangi fayl nomlari (kengaytmasiz). FAQAT XADICHA_VOCAB_FILES=1 bo'lsa
    ishlatiladi — nomlar Gemini'ga lug'at sifatida yuboriladi (maxfiylik)."""
    from pathlib import Path as _P

    items = []
    for d in ("Desktop", "Downloads", "Documents"):
        try:
            for p in (_P.home() / d).iterdir():
                if not p.name.startswith(".") and p.is_file():
                    items.append((p.stat().st_mtime, p.stem))
        except OSError:
            continue
    return list(dict.fromkeys(n for _, n in sorted(items, reverse=True) if 2 <= len(n) <= 60))[:limit]


@dataclass
class Vocabulary:
    """Maxsus lug'at (STT'ga ishora) va tuzatish lug'ati (natijaga qo'llanadi)."""

    terms: list[str] = field(default_factory=lambda: list(DEFAULT_TERMS))
    corrections: dict[str, str] = field(default_factory=dict)
    source: str = "default"

    @classmethod
    def load(cls, path: Path | None) -> Vocabulary:
        if path is None or not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("lug'at fayli o'qilmadi (%s): %s", path, e)
            return cls(source=f"xato: {path.name}")
        terms = [str(t).strip() for t in data.get("terms", []) if str(t).strip()]
        merged = list(dict.fromkeys(DEFAULT_TERMS + terms))[:1000]   # Gemini: 1000 tagacha atama
        corr = {str(k): str(v) for k, v in (data.get("corrections") or {}).items() if str(k).strip()}
        return cls(merged, corr, str(path))

    def correct(self, text: str) -> str:
        """Tuzatishlar: so'z chegarasi bo'yicha, katta-kichik harfga befarq ("telegramni" → "Telegram'ni" emas,
        faqat lug'atdagi aniq ibora almashtiriladi). Avval o'zbekcha apostroflar bir xillashtiriladi."""
        text = normalize_uz(text)
        for wrong, right in sorted(self.corrections.items(), key=lambda kv: -len(kv[0])):
            text = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", right, text, flags=re.I)
        return text

    def public(self) -> dict[str, Any]:
        return {"terms": len(self.terms), "corrections": len(self.corrections), "source": self.source}


def wav_bytes(audio: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    """float32 [-1, 1] mono → 16-bit PCM WAV (xotirada, diskka yozilmaydi)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def is_silence(audio: np.ndarray) -> bool:
    if audio.size < SAMPLE_RATE // 4:
        return True
    frame = SAMPLE_RATE // 50   # 20 ms
    n = audio.size // frame
    if n == 0:
        return True
    rms = np.sqrt(np.mean(np.square(audio[: n * frame].reshape(n, frame).astype(np.float32)), axis=1))
    return float(np.percentile(rms, 95)) < MIN_SPEECH_RMS


class GeminiTranscriber:
    """Gemini Transcribe (Interactions API, `gemini-3.5-transcribe`): avtomatik til, code-switching, lug'at."""

    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_s: float = 30.0, client: Any = None):
        from ..providers.base import ProviderError

        if not api_key:
            raise ProviderError("GEMINI_API_KEY o'rnatilmagan — Gemini Transcribe ishlamaydi.", kind="config")
        self.model = model
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
                api_version="v1beta", timeout=int(timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1)))
        self._client = client

    def transcribe(self, audio: np.ndarray, language: str | None, vocabulary: Vocabulary) -> str:
        from ..providers.gemini_provider import classify_error

        cfg: dict[str, Any] = {}
        if vocabulary.terms:
            cfg["custom_vocabulary"] = vocabulary.terms
        if language in BCP47:
            cfg["language_codes"] = [BCP47[language]]   # majburiy til (CLI --lang); odatda avtomatik
        body: dict[str, Any] = {
            "model": self.model,
            "input": [{"type": "audio", "data": base64.b64encode(wav_bytes(audio)).decode(), "mime_type": "audio/wav"}],
        }
        if cfg:
            body["generation_config"] = {"transcription_config": cfg}
        try:
            r = self._client.interactions.create(**body)
        except Exception as e:  # noqa: BLE001
            raise classify_error(e, "Gemini Transcribe") from e
        status = str(getattr(r, "status", "") or "")
        if status and status not in ("completed", "incomplete"):
            from ..providers.base import ProviderError

            raise ProviderError(f"Gemini Transcribe: holat {status}", kind="server")
        return str(getattr(r, "output_text", "") or "").strip()


class SpeechRecognizer:
    """Bitta kirish nuqtasi: `transcribe(audio, language, prior)` → Transcript (provayder ma'lumoti bilan)."""

    def __init__(self, whisper: Any, gemini: GeminiTranscriber | None = None, mode: str = "auto",
                 vocabulary: Vocabulary | None = None, gemini_error: str = "", clock=time.monotonic):
        self.whisper = whisper
        self.gemini = gemini
        self.mode = mode if mode in STT_MODES else "auto"
        self.vocabulary = vocabulary or Vocabulary()
        self._clock = clock
        self._lock = threading.Lock()
        self._down_until = 0.0
        self.gemini_error = redact(gemini_error)
        self.last_provider = ""
        self.last_model = ""
        self.last_fallback_reason = ""

    # --- holat ---
    @property
    def engine(self) -> str:
        """Hozir ishlatiladigan provayder (status va iz uchun)."""
        return "gemini" if self._gemini_ready() else f"whisper:{getattr(self.whisper, 'engine', '')}"

    offline = False   # oflayn rejim: faqat lokal Whisper

    def _gemini_ready(self) -> bool:
        return (not self.offline and self.mode in ("auto", "gemini") and self.gemini is not None
                and self._clock() >= self._down_until)

    def set_mode(self, mode: str) -> None:
        if mode in STT_MODES:
            self.mode = mode

    def info(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "offline": self.offline,
            "active": "gemini" if self._gemini_ready() else "whisper",
            "gemini": {"model": getattr(self.gemini, "model", ""), "configured": self.gemini is not None,
                       "available": self._gemini_ready(), "error": self.gemini_error,
                       "retry_in_s": max(0, int(self._down_until - self._clock()))},
            "whisper": {"engine": getattr(self.whisper, "engine", ""), "model": getattr(self.whisper, "model_name", "")},
            "last": {"provider": self.last_provider, "model": self.last_model, "fallback_reason": self.last_fallback_reason},
            "vocabulary": self.vocabulary.public(),
        }

    # --- aniqlash ---
    def _finish(self, t: Transcript, provider: str, model: str, fallback_from: str = "", reason: str = "") -> Transcript:
        if t.text:
            t.text = self.vocabulary.correct(t.text)
        t.provider, t.model = provider, model
        t.fallback_from, t.fallback_reason = fallback_from, reason
        self.last_provider, self.last_model, self.last_fallback_reason = provider, model, reason
        return t

    def _whisper(self, audio: np.ndarray, language: str | None, prior: str | None,
                 fallback_from: str = "", reason: str = "") -> Transcript:
        t = self.whisper.transcribe(audio, language, prior=prior)
        engine = getattr(self.whisper, "engine", "")
        return self._finish(t, f"whisper:{engine}" if engine else "whisper", getattr(self.whisper, "model_name", ""),
                            fallback_from, reason)

    def transcribe(self, audio: np.ndarray, language: str | None = None, prior: str | None = None) -> Transcript:
        if self.mode == "whisper" or self.offline:
            return self._whisper(audio, language, prior)
        if self.gemini is None:
            # auto: kalit yo'q — Whisper tanlov (zaxira emas); gemini: so'ralgan, lekin mavjud emas — sabab yoziladi
            if self.mode == "gemini":
                return self._whisper(audio, language, prior, "gemini", self.gemini_error or "Gemini Transcribe sozlanmagan")
            return self._whisper(audio, language, prior)
        if is_silence(audio):
            # Jimlik — hech qanday so'rov yuborilmaydi (pul va vaqt tejaladi, Whisper "gallyutsinatsiyasi" ham yo'q)
            return self._finish(Transcript("", language or "", 0.0, True), "gemini", self.gemini.model)
        if not self._gemini_ready():
            return self._whisper(audio, language, prior, "gemini", self.gemini_error or "Gemini Transcribe vaqtincha o'chiq")
        from ..providers.base import ProviderError

        try:
            text = self.gemini.transcribe(audio, language, self.vocabulary)
        except ProviderError as e:
            kind = getattr(e, "kind", "error")
            with self._lock:
                self.gemini_error = redact(str(e))
                self._down_until = self._clock() + _COOLDOWN.get(kind, 30.0)
            log.warning("Gemini Transcribe ishlamadi (%s): %s — Whisper ishlatiladi", kind, self.gemini_error)
            return self._whisper(audio, language, prior, "gemini", self.gemini_error)
        self.gemini_error = ""
        from ..lang import detect_text_language

        if language in SUPPORTED:
            lang, prob = language, 1.0
        else:
            guess = detect_text_language(text, prior or "uz") if text else None
            lang, prob = (guess.lang, float(guess.confidence)) if guess else (prior or "uz", 0.0)
        # Gemini so'z darajasidagi ishonchni bermaydi — None (taxmin qilinmaydi)
        return self._finish(Transcript(text, lang, prob, lang in SUPPORTED, detected_raw="gemini"), "gemini",
                            self.gemini.model)


def make_recognizer(cfg: Any, whisper: Any) -> SpeechRecognizer:
    vocab = Vocabulary.load(Path(cfg.vocabulary_file) if getattr(cfg, "vocabulary_file", "") else None)
    # Foydalanuvchi ilovalari nomlari (doim) va fayl nomlari (faqat ruxsat bilan) lug'atga qo'shiladi
    import os as _os

    extra = installed_app_names() if getattr(cfg, "vocab_apps", True) else []
    if _os.getenv("XADICHA_VOCAB_FILES", "").strip() in ("1", "true", "yes"):
        extra += recent_file_names()
    vocab.terms = list(dict.fromkeys(vocab.terms + extra))[:1000]
    mode = getattr(cfg, "stt_provider", "auto")
    gemini, err = None, ""
    if mode in ("auto", "gemini") and getattr(cfg, "gemini_api_key", ""):
        try:
            gemini = GeminiTranscriber(cfg.gemini_api_key, cfg.gemini_stt_model, getattr(cfg, "gemini_timeout_s", 30.0))
        except Exception as e:  # noqa: BLE001 — SDK yo'q va h.k.: Whisper ishlaydi, sabab statusda
            err = redact(str(e))
    elif mode == "gemini":
        err = "GEMINI_API_KEY o'rnatilmagan — Gemini Transcribe ishlamaydi."
    return SpeechRecognizer(whisper, gemini, mode, vocab, gemini_error=err)
