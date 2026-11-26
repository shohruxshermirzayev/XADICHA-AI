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

from ..redaction import safe_env
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
        out = subprocess.run(["say", "-v", "?"], env=safe_env(), capture_output=True, text=True, timeout=5).stdout
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


TTS_CACHE_DIR: "os.PathLike[str] | None" = None   # service o'rnatadi: backend/data/tts_cache (git'ga qo'shilmaydi)
TTS_CACHE_MAX_CHARS = 80      # faqat qisqa javoblar ("Safari ochildi.") — foydalanuvchi ovozi hech qachon saqlanmaydi
TTS_CACHE_MAX_FILES = 300


def tts_cache_path(voice: str, pct: int, text: str):
    if TTS_CACHE_DIR is None or len(text) > TTS_CACHE_MAX_CHARS:
        return None
    import hashlib
    from pathlib import Path

    h = hashlib.sha256(f"{voice}|{pct}|{text}".encode()).hexdigest()[:32]
    return Path(TTS_CACHE_DIR) / f"{h}.mp3"


def _trim_cache(d) -> None:
    files = sorted(d.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    for p in files[: max(0, len(files) - TTS_CACHE_MAX_FILES)]:
        p.unlink(missing_ok=True)


def speech_chunks(text: str, first_min: int = 24, max_len: int = 220) -> list[str]:
    """Ovoz uchun bo'laklar: birinchisi — birinchi gap (tez boshlash uchun qisqa), keyingilari — gaplar guruhi."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s.strip()]
    if len(sents) <= 1:
        return [text.strip()] if text.strip() else []
    out: list[str] = []
    cur = ""
    for s in sents:
        limit = first_min if not out else max_len
        if cur and len(cur) >= limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


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
        """Gapirishni to'xtatish (uzilish) — bo'laklar navbati ham bekor qilinadi."""
        with self._lock:
            self._gen = getattr(self, "_gen", 0) + 1
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

    def stream_push(self, text: str, lang: str) -> bool:
        """Oqimli javobning tayyor gapi — navbatga; birinchisi darhol ijro etiladi, keyingilari ketma-ket.
        stop() navbatni bekor qiladi. Qaytaradi: navbatga qo'yildimi."""
        import queue as _q

        if not text or not self.available(lang):
            return False
        text = speech_text(text, lang)
        with self._lock:
            gen = getattr(self, "_gen", 0)
            if getattr(self, "_sq", None) is None or getattr(self, "_sq_gen", -1) != gen:
                self._sq, self._sq_gen = _q.Queue(), gen
                threading.Thread(target=self._stream_worker, args=(self._sq, gen, lang), daemon=True).start()
            self._sq.put(text)
        return True

    def stream_end(self) -> None:
        with self._lock:
            if getattr(self, "_sq", None) is not None:
                self._sq.put(None)
                self._sq = None

    def _stream_worker(self, q, gen: int, lang: str) -> None:
        import asyncio as _a

        while True:
            item = q.get()
            if item is None or getattr(self, "_gen", 0) != gen:
                return
            cmd: list[str] | None = None
            if self.engine == "edge":
                try:
                    import edge_tts

                    voice = self.voices.get(lang) or EDGE_VOICES.get(lang, EDGE_VOICES["en"])
                    pct = int((self.rate - 175) / 175 * 100)
                    path = tts_cache_path(voice, pct, item)
                    if path is None or not path.exists():
                        fd, tmp = tempfile.mkstemp(suffix=".mp3")
                        os.close(fd)
                        _a.run(edge_tts.Communicate(item, voice, rate=f"{pct:+d}%").save(tmp))
                        if path is not None:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            os.replace(tmp, path)
                        else:
                            path = tmp
                    cmd = ["afplay", str(path)]
                except Exception:  # noqa: BLE001
                    cmd = None
            elif platform.system() == "Darwin":
                cmd = ["say", "-v", self.voice_for(lang) or "", "-r", str(self.rate), item]
            if cmd is None:
                continue
            with self._lock:
                prev = self._proc
            if prev is not None:
                prev.wait()   # oldingi gap tugashini kutamiz (keyingisi shu vaqtda tayyorlandi)
            with self._lock:
                if getattr(self, "_gen", 0) != gen:
                    return
                self._proc = subprocess.Popen(cmd, env=safe_env())

    def _play_chunks(self, parts: list[str], synth, block: bool) -> bool:
        """Javob gaplarga bo'linadi: birinchi gap tayyor bo'lishi bilan ijro boshlanadi, qolganlari fonda
        sintez qilinadi va navbat bilan ijro etiladi. stop() — butun navbatni bekor qiladi."""
        first = synth(parts[0])
        if first is None:
            return False
        with self._lock:
            gen = getattr(self, "_gen", 0)
        self._spawn(["afplay", first], False)
        self.last_first_audio_chunk = parts[0]

        def rest() -> None:
            nxt: dict[int, str | None] = {}
            prefetch = threading.Thread(target=lambda: nxt.update({i: synth(c) for i, c in enumerate(parts[1:], 1)}),
                                        daemon=True)
            prefetch.start()
            for i in range(1, len(parts)):
                while i not in nxt and prefetch.is_alive():
                    if getattr(self, "_gen", 0) != gen:
                        return
                    threading.Event().wait(0.02)
                with self._lock:
                    proc = self._proc
                if proc is not None:
                    proc.wait()
                if getattr(self, "_gen", 0) != gen or not nxt.get(i):
                    return
                with self._lock:
                    if getattr(self, "_gen", 0) != gen:
                        return
                    self._proc = subprocess.Popen(["afplay", nxt[i]], env=safe_env())

        th = threading.Thread(target=rest, daemon=True)
        th.start()
        if block:
            th.join()
            with self._lock:
                proc = self._proc
            if proc is not None:
                proc.wait()
        return True

    def _spawn(self, cmd: list[str], block: bool) -> bool:
        with self._lock:
            self._proc = subprocess.Popen(cmd, env=safe_env())
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

        def synth(chunk: str) -> str | None:
            cached = tts_cache_path(voice, pct, chunk)
            if cached is not None and cached.exists() and cached.stat().st_size > 0:
                return str(cached)   # takroriy qisqa javob — tarmoqsiz, darhol
            fd, out = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)

            async def _save():
                await edge_tts.Communicate(chunk, voice, rate=f"{pct:+d}%").save(out)

            try:
                asyncio.run(_save())
            except Exception:  # noqa: BLE001 — internet yo'q va h.k.
                return None
            if cached is not None:
                try:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(out, cached)
                    _trim_cache(cached.parent)
                    return str(cached)
                except OSError:
                    pass
            return out

        parts = speech_chunks(text) if platform.system() == "Darwin" else [text]
        if len(parts) > 1:
            return self._play_chunks(parts, synth, block)
        path = synth(text)
        if path is None:
            return False
        if platform.system() == "Darwin":
            return self._spawn(["afplay", path], block)
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        return False
