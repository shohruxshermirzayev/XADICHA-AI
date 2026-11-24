"""Nutqni matnga aylantirish (faster-whisper, lokal va bepul) + tilni aniqlash.

Muhim: Whisper o'zbek nutqini ko'pincha turk, qozoq yoki boshqa tillar deb aniqlaydi.
Shuning uchun til faqat uch qo'llab-quvvatlanadigan til (uz/ru/en) orasidan tanlanadi
(cheklangan tilni aniqlash), so'ng matn aynan shu tilda olinadi. Kerak bo'lsa, til
majburan berilishi mumkin (`--lang uz`).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
SUPPORTED = ("uz", "ru", "en")

# Kontekst: Whisper'ni ilova nomlari va buyruq so'zlariga moslaydi
PROMPTS = {
    "uz": ("Safari ni och. Telegram'ni och. Notes ni och. Papka yarat. Google'da qidir. "
           "YouTube'da qidirib qo'shiqni qo'y. Musiqa, qo'shiq, video, brauzer, kompyuter, ilova, sayt."),
    "ru": "Открой Safari. Открой Telegram. Открой Notes. Создай папку. Найди в Google. Включи песню на YouTube.",
    "en": "Open Safari. Open Telegram. Open Notes. Create a folder. Search Google. Play a song on YouTube.",
}


@dataclass
class Transcript:
    text: str
    language: str
    probability: float
    supported: bool
    detected_raw: str = ""   # Whisper o'zi aniqlagan til (cheklovsiz) — tahlil uchun


def pick_language(all_probs: list[tuple[str, float]] | None, raw_lang: str,
                  allowed: tuple[str, ...] = SUPPORTED) -> tuple[str, float]:
    """Ehtimolliklar ro'yxatidan faqat ruxsat etilgan tillar orasidan eng yuqorisini tanlaydi."""
    probs = dict(all_probs or [])
    best = max(allowed, key=lambda lang: probs.get(lang, 0.0))
    if probs.get(best, 0.0) > 0:
        return best, float(probs[best])
    # Ehtimolliklar yo'q bo'lsa: aniqlangan til ruxsat etilgan bo'lsa o'shani, aks holda o'zbekcha
    return (raw_lang if raw_lang in allowed else "uz"), 0.0


def mlx_available() -> bool:
    import platform

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def mlx_repo(model_name: str) -> str:
    if model_name.endswith("turbo"):
        return f"mlx-community/whisper-{model_name}"
    return f"mlx-community/whisper-{model_name}-mlx"


class Listener:
    """engine: "auto" (Apple Silicon'da MLX — grafik protsessorda, aks holda faster-whisper), "mlx", "faster"."""

    def __init__(self, model_name: str = "large-v3-turbo", engine: str = "auto"):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()
        if engine == "auto":
            engine = "mlx" if mlx_available() else "faster"
        self.engine = engine

    def warmup(self) -> None:
        """Modelni oldindan yuklaydi (birinchi ovozli buyruq kutib qolmasligi uchun)."""
        try:
            if self.engine == "mlx":
                self._mlx(np.zeros(SAMPLE_RATE, dtype=np.float32), "uz")
            else:
                self._load()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("xadicha").exception("STT warmup xatosi")

    def _mlx(self, audio: np.ndarray, language: str | None) -> tuple[str, str]:
        import mlx_whisper

        r = mlx_whisper.transcribe(audio, path_or_hf_repo=mlx_repo(self.model_name), language=language,
                                   initial_prompt=PROMPTS.get(language or ""), condition_on_previous_text=False,
                                   verbose=None)
        return str(r.get("text", "")).strip(), str(r.get("language") or language or "")

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        return self._model

    def record_until(self, stop: threading.Event, max_seconds: float = 30.0) -> np.ndarray:
        """`stop` hodisasigacha (yoki max_seconds) mikrofondan yozadi."""
        import sounddevice as sd

        chunks: list[np.ndarray] = []

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            chunks.append(indata.copy())

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
            stop.wait(timeout=max_seconds)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)[:, 0]

    def detect(self, audio: np.ndarray) -> tuple[str, float, str]:
        """(tanlangan til, ehtimollik, Whisper'ning cheklovsiz aniqlagani)."""
        model = self._load()
        try:
            raw, _p, all_probs = model.detect_language(audio, vad_filter=True)
        except (AttributeError, TypeError):   # faster-whisper'ning eski versiyalari
            _segs, info = model.transcribe(audio, beam_size=1, vad_filter=True)
            raw, all_probs = info.language, getattr(info, "all_language_probs", None)
        lang, prob = pick_language(all_probs, raw)
        return lang, prob, raw

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> Transcript:
        """language=None — uz/ru/en orasidan avtomatik tanlash; "uz"/"ru"/"en" — majburiy til."""
        if audio.size < SAMPLE_RATE // 4:
            return Transcript("", language or "", 0.0, True)
        if self.engine == "mlx":
            try:
                return self._transcribe_mlx(audio, language)
            except Exception:  # noqa: BLE001 — MLX ishlamasa faster-whisper'ga o'tamiz
                import logging

                logging.getLogger("xadicha").exception("MLX STT xatosi, faster-whisper'ga o'tildi")
                self.engine = "faster"
        model = self._load()
        raw = ""
        prob = 1.0
        if language is None:
            language, prob, raw = self.detect(audio)
        segments, _info = model.transcribe(audio, language=language, beam_size=5, vad_filter=True,
                                           initial_prompt=PROMPTS.get(language))
        text = " ".join(s.text.strip() for s in segments).strip()
        if len(text) > 40 and text.rstrip(".") in PROMPTS.get(language, ""):
            text = ""   # jimlikda Whisper ba'zan kontekst matnini takrorlaydi — bu nutq emas
        return Transcript(text, language, prob, language in SUPPORTED, detected_raw=raw)

    def _transcribe_mlx(self, audio: np.ndarray, language: str | None) -> Transcript:
        text, lang = self._mlx(audio, language)
        raw = ""
        if language is None and lang not in SUPPORTED:
            # MLX tilni cheklovsiz aniqlaydi — qo'llab-quvvatlanmaydigan til chiqsa, o'zbekcha deb qayta o'qiymiz
            raw = lang
            text, lang = self._mlx(audio, "uz")
        if len(text) > 40 and text.rstrip(".") in PROMPTS.get(lang, ""):
            text = ""
        return Transcript(text, lang, 1.0, lang in SUPPORTED, detected_raw=raw)
