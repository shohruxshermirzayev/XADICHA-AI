"""Nutqni matnga aylantirish (faster-whisper, lokal va bepul) + tilni aniqlash.

Muhim: Whisper o'zbek nutqini ko'pincha turk, qozoq yoki boshqa tillar deb aniqlaydi.
Shuning uchun til faqat uch qo'llab-quvvatlanadigan til (uz/ru/en) orasidan tanlanadi
(cheklangan tilni aniqlash), so'ng matn aynan shu tilda olinadi. Kerak bo'lsa, til
majburan berilishi mumkin (`--lang uz`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
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


def rms_level(samples: np.ndarray) -> float:
    """Ovoz balandligi 0..1 (RMS * 6, yuqoridan kesilgan) — brauzerdagi eski hisob bilan bir xil shkala."""
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))))
    return min(1.0, rms * 6.0)


class Endpointer:
    """Gapirib bo'linganini sezish (energiya asosida, sof — testlanadi).

    Algoritm:
      - Kalibrlash: birinchi `calib_s` da fon shovqini (median RMS) o'lchanadi.
      - Moslashuvchan shovqin: nutq bo'lmagan bo'laklarda fon darajasi sekin yangilanadi (EMA) — konditsioner
        yoqilsa yoki xona tinchisa ham chegara mos keladi.
      - Gisterezis: nutq boshlanishi uchun yuqoriroq chegara (`on_ratio`), davom etishi uchun pastroq (`off_ratio`) —
        so'z oxiridagi pasayishda erta kesib qo'ymaydi.
      - Pauzaga chidamlilik: uzoqroq gapirilgan bo'lsa (> `long_speech_s`), jimlik chegarasi biroz uzayadi
        (gap ichidagi o'ylash pauzasi ko'proq bo'ladi).
      - Minimal nutq: `min_speech_s` dan qisqa tovush (stol taqillashi) nutq hisoblanmaydi.
      - Nutq bo'lmasa — `no_speech_s` dan keyin; umumiy chegara — chaqiruvchidagi `max_seconds`.
    Qiymatlar real mikrofonda kalibrlanmagan — scripts/mac_selftest.py --only vad bilan o'lchanadi.
    """

    def __init__(self, silence_s: float = 0.9, min_speech_s: float = 0.2, no_speech_s: float = 6.0,
                 calib_s: float = 0.3, on_ratio: float = 3.0, off_ratio: float = 1.8, min_level: float = 0.008,
                 long_speech_s: float = 1.5, long_silence_s: float = 1.2, noise_alpha: float = 0.05):
        self.silence_s, self.min_speech_s, self.no_speech_s = silence_s, min_speech_s, no_speech_s
        self.calib_s, self.on_ratio, self.off_ratio, self.min_level = calib_s, on_ratio, off_ratio, min_level
        self.long_speech_s, self.long_silence_s, self.noise_alpha = long_speech_s, long_silence_s, noise_alpha
        self.t = 0.0
        self.noise: list[float] = []
        self.floor: float | None = None
        self.in_speech = False
        self.speech_run = 0.0
        self.speech_total = 0.0
        self.silence_run = 0.0
        self.heard = False
        self.first_speech_t: float | None = None
        self.last_speech_t: float | None = None
        self.reason = ""

    def _threshold(self, ratio: float) -> float:
        return max(self.min_level, (self.floor or 0.0) * ratio)

    @property
    def threshold(self) -> float:
        return self._threshold(self.on_ratio)

    @property
    def endpoint_delay_s(self) -> float:
        """Oxirgi nutq bo'lagidan to'xtash qaroriga qadar o'tgan vaqt (kechikish)."""
        return 0.0 if self.last_speech_t is None else max(0.0, self.t - self.last_speech_t)

    def feed(self, rms: float, dt: float) -> bool:
        """Bitta bo'lak (RMS, davomiyligi). True — yozishni to'xtatish vaqti keldi."""
        self.t += dt
        if self.floor is None:
            if self.t <= self.calib_s:
                self.noise.append(rms)
                return False
            self.floor = sorted(self.noise)[len(self.noise) // 2] if self.noise else 0.0
        thr = self._threshold(self.off_ratio if self.in_speech else self.on_ratio)
        if rms > thr:
            self.speech_run += dt
            self.silence_run = 0.0
            if self.speech_run >= self.min_speech_s and not self.in_speech:
                self.in_speech = True
                self.heard = True
                self.first_speech_t = self.first_speech_t or (self.t - self.speech_run)
            if self.in_speech:
                self.speech_total += dt
                self.last_speech_t = self.t
        else:
            if not self.in_speech:
                self.speech_run = 0.0
                # Faqat nutq yo'q paytda fon yangilanadi (nutqni shovqin deb o'rganib qolmaslik uchun)
                self.floor = (1 - self.noise_alpha) * self.floor + self.noise_alpha * rms
            self.silence_run += dt
            limit = self.long_silence_s if self.speech_total >= self.long_speech_s else self.silence_s
            if self.in_speech and self.silence_run >= limit:
                self.in_speech = False
                self.speech_run = 0.0
                self.reason = "silence"
                return True
        if not self.heard and self.t >= self.no_speech_s:
            self.reason = "no_speech"
            return True
        return False


# Whisper jimlikda ba'zan "o'ylab topadigan" iboralar — buyruq emas, bajarilmaydi
_HALLUCINATIONS = ("продолжение следует", "субтитры", "спасибо за просмотр", "редактор субтитров",
                   "thank you for watching", "thanks for watching", "subtitles by", "please subscribe",
                   "obuna bo'ling", "rahmat tomosha")


def is_hallucination(text: str) -> bool:
    low = text.lower().strip(" .!?…")
    return bool(low) and any(h in low for h in _HALLUCINATIONS)


def asr_confidence(segments: list[tuple[float, float, int]]) -> float | None:
    """Nutq tanish ishonchi 0..1: segmentlar avg_logprob'ining (matn uzunligi bo'yicha vaznli) eksponentasi,
    "nutq yo'q" ehtimolligi bilan kamaytirilgan. Kiruvchi: [(avg_logprob, no_speech_prob, belgilar soni)].
    Bu Whisper'ning o'z ishonch ko'rsatkichi — haqiqiy aniqlik (WER) emas."""
    items = [(lp, ns, max(1, n)) for lp, ns, n in segments if lp is not None]
    if not items:
        return None
    total = sum(n for _, _, n in items)
    mean_lp = sum(lp * n for lp, _, n in items) / total
    mean_ns = sum((ns or 0.0) * n for _, ns, n in items) / total
    conf = float(np.exp(min(0.0, mean_lp))) * (1.0 - min(1.0, max(0.0, mean_ns)))
    return round(max(0.0, min(1.0, conf)), 3)


@dataclass
class Transcript:
    text: str
    language: str
    probability: float        # til ehtimolligi
    supported: bool
    detected_raw: str = ""   # Whisper o'zi aniqlagan til (cheklovsiz) — tahlil uchun
    asr_confidence: float | None = None   # nutq tanish ishonchi (0..1); noma'lum bo'lsa None
    provider: str = ""          # haqiqatan ishlagan STT: "gemini" | "whisper:mlx" | "whisper:faster"
    model: str = ""
    fallback_from: str = ""     # zaxiraga o'tilgan bo'lsa — qaysi provayderdan
    fallback_reason: str = ""


PRIOR_BOOST = 0.15   # tanlangan tilga qo'shimcha og'irlik — "prior", majburlash emas


def pick_language(all_probs: list[tuple[str, float]] | None, raw_lang: str,
                  allowed: tuple[str, ...] = SUPPORTED, prior: str | None = None) -> tuple[str, float]:
    """Ehtimolliklar ro'yxatidan faqat ruxsat etilgan tillar orasidan eng yuqorisini tanlaydi.
    prior — foydalanuvchi tanlagan til: unga kichik qo'shimcha beriladi (aniq boshqa til bo'lsa, u yutadi)."""
    probs = dict(all_probs or [])

    def score(lang: str) -> float:
        return probs.get(lang, 0.0) + (PRIOR_BOOST if lang == prior and probs.get(lang, 0.0) > 0 else 0.0)

    best = max(allowed, key=score)
    if probs.get(best, 0.0) > 0:
        return best, float(probs[best])
    # Ehtimolliklar yo'q bo'lsa: aniqlangan til ruxsat etilgan bo'lsa o'shani, aks holda tanlangan til / o'zbekcha
    return (raw_lang if raw_lang in allowed else (prior if prior in allowed else "uz")), 0.0


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
        self.device: str | None = None   # mikrofon nomi (None — tizim standarti)
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
        text, lang, _conf = self._mlx_full(audio, language)
        return text, lang

    def _mlx_full(self, audio: np.ndarray, language: str | None) -> tuple[str, str, float | None]:
        import mlx_whisper

        r = mlx_whisper.transcribe(audio, path_or_hf_repo=mlx_repo(self.model_name), language=language,
                                   initial_prompt=PROMPTS.get(language or ""), condition_on_previous_text=False,
                                   verbose=None)
        segs = [(sg.get("avg_logprob"), sg.get("no_speech_prob", 0.0), len(str(sg.get("text", ""))))
                for sg in (r.get("segments") or []) if isinstance(sg, dict)]
        return str(r.get("text", "")).strip(), str(r.get("language") or language or ""), asr_confidence(segs)

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        return self._model

    def record_until(self, stop: threading.Event, max_seconds: float = 30.0,
                     on_level: Callable[[float], None] | None = None,
                     endpointer: Endpointer | None = None) -> np.ndarray:
        """`stop` hodisasigacha (yoki max_seconds) mikrofondan yozadi.

        on_level — har bir bo'lak uchun ovoz balandligi (0..1, RMS asosida); interfeys vizualizatsiyasi uchun.
        Mikrofon faqat shu yerda ochiladi — brauzer alohida yozib olmaydi.
        """
        import sounddevice as sd

        chunks: list[np.ndarray] = []

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            chunks.append(indata.copy())
            if on_level is not None:
                try:
                    on_level(rms_level(indata))
                except Exception:  # noqa: BLE001 — vizualizatsiya xatosi yozuvni buzmasin
                    pass
            if endpointer is not None:
                rms = float(np.sqrt(np.mean(np.square(indata.astype(np.float32))))) if len(indata) else 0.0
                if endpointer.feed(rms, frames / SAMPLE_RATE):
                    stop.set()   # gapirib bo'lindi — yozish avtomatik to'xtaydi

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback,
                            device=self.device or None):
            stop.wait(timeout=max_seconds)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)[:, 0]

    def detect(self, audio: np.ndarray, prior: str | None = None) -> tuple[str, float, str]:
        """(tanlangan til, ehtimollik, Whisper'ning cheklovsiz aniqlagani)."""
        model = self._load()
        try:
            raw, _p, all_probs = model.detect_language(audio, vad_filter=True)
        except (AttributeError, TypeError):   # faster-whisper'ning eski versiyalari
            _segs, info = model.transcribe(audio, beam_size=1, vad_filter=True)
            raw, all_probs = info.language, getattr(info, "all_language_probs", None)
        lang, prob = pick_language(all_probs, raw, prior=prior)
        return lang, prob, raw

    def transcribe(self, audio: np.ndarray, language: str | None = None, prior: str | None = None) -> Transcript:
        """language=None — uz/ru/en orasidan avtomatik tanlash (prior — tanlangan tilga ustunlik);
        "uz"/"ru"/"en" — majburiy til."""
        if audio.size < SAMPLE_RATE // 4:
            return Transcript("", language or "", 0.0, True)
        if self.engine == "mlx":
            try:
                return self._transcribe_mlx(audio, language, prior)
            except Exception:  # noqa: BLE001 — MLX ishlamasa faster-whisper'ga o'tamiz
                import logging

                logging.getLogger("xadicha").exception("MLX STT xatosi, faster-whisper'ga o'tildi")
                self.engine = "faster"
        model = self._load()
        raw = ""
        prob = 1.0
        if language is None:
            language, prob, raw = self.detect(audio, prior)
        segments, _info = model.transcribe(audio, language=language, beam_size=5, vad_filter=True,
                                           initial_prompt=PROMPTS.get(language))
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
        conf = asr_confidence([(getattr(s, "avg_logprob", None), getattr(s, "no_speech_prob", 0.0), len(s.text))
                               for s in segments])
        if (len(text) > 40 and text.rstrip(".") in PROMPTS.get(language, "")) or is_hallucination(text):
            text, conf = "", None   # jimlikda Whisper ba'zan matn "o'ylab topadi" — bu nutq emas, bajarilmaydi
        return Transcript(text, language, prob, language in SUPPORTED, detected_raw=raw, asr_confidence=conf)

    def _transcribe_mlx(self, audio: np.ndarray, language: str | None, prior: str | None = None) -> Transcript:
        text, lang, conf = self._mlx_full(audio, language)
        raw = ""
        if language is None and lang not in SUPPORTED:
            # MLX tilni cheklovsiz aniqlaydi — qo'llab-quvvatlanmaydigan til chiqsa (ko'pincha o'zbek → turk/qozoq),
            # tanlangan til (yoki o'zbekcha) deb qayta o'qiymiz
            raw = lang
            text, lang, conf = self._mlx_full(audio, prior if prior in SUPPORTED else "uz")
        if (len(text) > 40 and text.rstrip(".") in PROMPTS.get(lang, "")) or is_hallucination(text):
            text, conf = "", None
        # MLX til ehtimolligini bermaydi — 1.0 emas, noma'lum deb belgilaymiz
        return Transcript(text, lang, 0.0, lang in SUPPORTED, detected_raw=raw, asr_confidence=conf)
