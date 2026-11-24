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

MAC_VOICES = {"en": "Samantha", "ru": "Milena"}
EDGE_VOICES = {"uz": "uz-UZ-MadinaNeural", "ru": "ru-RU-SvetlanaNeural", "en": "en-US-JennyNeural"}


class Speaker:
    def __init__(self, engine: str = "system", rate: int = 175, voices: dict[str, str] | None = None,
                 enabled: bool = True):
        self.engine = engine
        self.rate = rate
        self.voices = {k: v for k, v in (voices or {}).items() if v}
        self.enabled = enabled
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def available(self, lang: str) -> bool:
        if not self.enabled:
            return False
        if self.engine == "edge":
            return True
        if platform.system() == "Darwin":
            return bool(self.voices.get(lang) or MAC_VOICES.get(lang))
        return platform.system() == "Windows"

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
        self.stop()
        if self.engine == "edge":
            return self._edge(text, lang, block)
        if platform.system() == "Darwin":
            voice = self.voices.get(lang) or MAC_VOICES[lang]
            return self._spawn(["say", "-v", voice, "-r", str(self.rate), text], block)
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
