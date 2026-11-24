"""Nutq sintezi (ayol ovozi).

Dvigatellar:
- system: macOS `say` (Samantha — en, Milena — ru), Windows SAPI (pyttsx3).
  macOS va Windowsda o'zbekcha tizim ovozi yo'q — bunday holda "edge" tavsiya etiladi.
- edge: Microsoft Edge neyron ovozlari (uz-UZ-MadinaNeural, ru-RU-SvetlanaNeural, en-US-JennyNeural).
  Internet kerak, `pip install edge-tts`. Rasmiy bo'lmagan xizmat — dissertatsiyada cheklov sifatida qayd etiladi.

O'zbekcha talaffuz sifati hali sinovdan o'tkazilmagan.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import threading

import re
from functools import lru_cache

MAC_VOICES = {"en": "Samantha", "ru": "Milena"}
# Afzal ko'rilgan ayol ovozlari (birinchi o'rnatilgani tanlanadi). macOS'da o'zbek tizim ovozi yo'q.
MAC_PREFERRED = {"en": ["Samantha", "Ava", "Allison", "Zoe", "Susan", "Karen"], "ru": ["Milena", "Katya"], "uz": []}
EDGE_VOICES = {"uz": "uz-UZ-MadinaNeural", "ru": "ru-RU-SvetlanaNeural", "en": "en-US-JennyNeural"}
_LOCALE = {"uz": "uz_", "ru": "ru_", "en": "en_"}


@lru_cache(maxsize=1)
def mac_voices() -> dict[str, str]:
    """O'rnatilgan macOS ovozlari: {nom: locale}. `say -v ?` natijasidan; bo'lmasa — bo'sh."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    voices = {}
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})\b", line)
        if m:
            voices[m.group(1).strip()] = m.group(2)
    return voices


def choose_mac_voice(lang: str, configured: str | None, installed: dict[str, str]) -> str | None:
    """Sozlangan ovoz o'rnatilgan bo'lsa — u; aks holda afzal ro'yxatdan; aks holda shu tildagi istalgan ovoz.
    Boshqa tildagi ovoz bilan "o'qitib" yuborilmaydi (o'zbek matnini rus ovozi buzib o'qiydi)."""
    if configured and (not installed or configured in installed):
        return configured
    for name in MAC_PREFERRED.get(lang, []):
        if name in installed:
            return name
    for name, loc in installed.items():
        if loc.startswith(_LOCALE.get(lang, "??")):
            return name
    if not installed and lang in MAC_VOICES:
        return MAC_VOICES[lang]   # ro'yxatni o'qib bo'lmadi — standart nom
    return None


def edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


_URL = re.compile(r"https?://([^/\s]+)[^\s]*")
_PATH = re.compile(r"~?/(?:[\w.\-]+/)+([\w.\-]+)")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_DOT = {"uz": " nuqta ", "ru": " точка ", "en": " dot "}
_PCT = {"uz": " foiz", "ru": " процентов", "en": " percent"}


def speech_text(text: str, lang: str) -> str:
    """Ovoz uchun matn (ko'rsatiladigan matndan ALOHIDA). Manzil — domen, yo'l — fayl nomi, belgilar — so'z.
    Kod, fayl nomi va domen buzilmaydi — faqat o'qilish shakli o'zgaradi."""
    t = _EMOJI.sub("", text)
    t = re.sub(r"\[(\d+)\]", "", t)                      # manba havolalari [1]
    t = re.sub(r"[*_`#>]+", "", t)                          # markdown belgilari
    t = _URL.sub(lambda m: m.group(1).removeprefix("www.").replace(".", _DOT.get(lang, " dot ")), t)
    t = _PATH.sub(lambda m: m.group(1), t)
    t = re.sub(r"(\d)\s*%", lambda m: m.group(1) + _PCT.get(lang, " percent"), t)
    if lang == "uz":
        # O'zbek lotin: o' g' — "o‘ g‘" (U+02BB), tutuq belgisi — U+02BC (neyron ovozlar shuni kutadi)
        t = re.sub(r"([OoGg])['’‘`ʼ]", lambda m: m.group(1) + "\u02bb", t)
        t = re.sub(r"(?<=\w)['’`](?=\w)", "\u02bc", t)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


class Speaker:
    def __init__(self, engine: str = "system", rate: int = 175, voices: dict[str, str] | None = None,
                 enabled: bool = True):
        self.engine = engine
        self.rate = rate
        self.voices = {k: v for k, v in (voices or {}).items() if v}
        self.enabled = enabled
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def voice_for(self, lang: str) -> str | None:
        """Shu til uchun haqiqatan ishlatiladigan ovoz (yo'q bo'lsa None)."""
        if self.engine == "edge":
            return (self.voices.get(lang) or EDGE_VOICES.get(lang)) if edge_available() else None
        if platform.system() == "Darwin":
            return choose_mac_voice(lang, self.voices.get(lang), mac_voices())
        if platform.system() == "Windows":
            return self.voices.get(lang) or "SAPI"
        return None

    def available(self, lang: str) -> bool:
        return self.enabled and self.voice_for(lang) is not None

    def stop(self) -> None:
        """Gapirishni to'xtatish (uzilish)."""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None

    def say(self, text: str, lang: str = "uz", block: bool = False) -> bool:
        """Matnni ovoz chiqarib aytadi. Ovoz mavjud bo'lmasa False qaytaradi."""
        if not text or not self.available(lang):
            return False
        self.stop()   # bir vaqtda faqat bitta ovoz — oldingisi to'xtatiladi
        text = speech_text(text, lang)
        if self.engine == "edge":
            return self._edge(text, lang, block)
        if platform.system() == "Darwin":
            voice = self.voice_for(lang)
            return self._spawn(["say", "-v", voice or "", "-r", str(self.rate), text], block)
        if platform.system() == "Windows":
            return self._sapi(text, lang)
        return False

    def _spawn(self, cmd: list[str], block: bool) -> bool:
        with self._lock:
            self._proc = subprocess.Popen(cmd)
            proc = self._proc
        if block:
            proc.wait()
        return True

    def _sapi(self, text: str, lang: str) -> bool:
        try:
            import pyttsx3
        except ImportError:
            return False
        engine = pyttsx3.init()
        engine.setProperty("rate", self.rate)
        wanted = self.voices.get(lang)
        for v in engine.getProperty("voices"):
            name = (v.name or "").lower()
            if (wanted and wanted.lower() in name) or (not wanted and "zira" in name and lang == "en"):
                engine.setProperty("voice", v.id)
                break
        engine.say(text)
        engine.runAndWait()
        return True

    def _edge(self, text: str, lang: str, block: bool) -> bool:
        try:
            import asyncio

            import edge_tts
        except ImportError:
            return False
        voice = self.voices.get(lang) or EDGE_VOICES.get(lang, EDGE_VOICES["en"])
        pct = int((self.rate - 175) / 175 * 100)
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)

        async def _save():
            await edge_tts.Communicate(text, voice, rate=f"{pct:+d}%").save(path)

        try:
            asyncio.run(_save())
        except Exception:  # noqa: BLE001 — internet yo'q va h.k.
            return False
        if platform.system() == "Darwin":
            return self._spawn(["afplay", path], block)
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        return False
