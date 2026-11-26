"""Buyruq rejimi uchun oqimli nutqni aniqlash — Gemini Live Transcription (`gemini-3.5-transcribe-live`).

Oqim: mikrofon (16 kHz, mono, 16-bit PCM, 64 ms bo'laklar) → WebSocket → oraliq (interim) matn real vaqtda
interfeysga → yakuniy matn. Mikrofon oqimi gap davomida uzilmaydi; ulanish o'rnatilguncha audio buferda turadi
(birinchi so'zlar yo'qolmaydi).

Yakunlash (o'lchovlar asosida, docs/VOICE_LATENCY.md):
  * server yakuniy matnni beradi VA mahalliy VAD gap tugaganini aytadi → darhol tugaydi;
  * mahalliy VAD gap tugadi desa, lekin yakuniy matn `final_grace_s` ichida kelmasa → oxirgi oraliq matn olinadi
    (`finalized_by="interim"` — metadata'da yoziladi, yashirilmaydi);
  * `audio_stream_end` ATAYIN yuborilmaydi: sinovlarda u yakuniy matnni 5–28 s kechiktirdi, jimlik oqimi esa ~0.7 s.
Ulanish yoki API xatosida buferdagi to'liq audio qaytariladi — chaqiruvchi uni Gemini Transcribe / Whisper'ga beradi.
Audio diskka yozilmaydi.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..redaction import redact
from .stt import SAMPLE_RATE, Endpointer

log = logging.getLogger("xadicha")
CHUNK_MS = 64          # 1024 kadr — hujjat tavsiyasi; 20 ms bo'laklar sinovda yakuniy matnni 12 s kechiktirdi
BCP47 = ["uz-UZ", "ru-RU", "en-US"]


@dataclass
class StreamResult:
    text: str = ""
    finalized_by: str = ""                 # "server" (yakuniy) | "local" (oraliq matn yakunlandi) | "empty" | "error"
    reason: str = ""                       # nima uchun shunday yakunlandi (diagnostika)
    audio: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))   # zaxira uchun (xotirada)
    error: str = ""
    marks: dict[str, int] = field(default_factory=dict)   # capture boshidan ms: connected, first_partial, speech_end, final
    model: str = ""


class MicSource:
    """Haqiqiy mikrofon (sounddevice RawInputStream)."""

    def __init__(self, device: Any = None):
        self.device = device
        self._s = None

    def start(self, on_chunk: Callable[[bytes], None]) -> None:
        import sounddevice as sd

        def cb(indata, frames, t, status):  # noqa: ARG001
            on_chunk(bytes(indata))

        self._s = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=self.device or None,
                                    blocksize=SAMPLE_RATE * CHUNK_MS // 1000, callback=cb)
        self._s.start()

    def stop(self) -> None:
        if self._s is not None:
            try:
                self._s.stop()
                self._s.close()
            except Exception:  # noqa: BLE001
                pass
            self._s = None


class LiveSTTPool:
    """Oldindan ochilgan Live Transcription sessiyasi (ulanishni qayta ishlatish): buyruq kelganda ulanish kutilmaydi.

    Doimiy event loop (alohida ipda) bitta TAYYOR sessiyani ushlab turadi; buyruq uni oladi, pool esa darhol keyingisini
    fonda ochadi. Sessiya `max_age_s` dan keyin yangilanadi (server cheklovi — 10 daqiqa). Sinov: 25 s bo'sh turgan
    sessiya nutqni to'g'ri tanidi (docs/VOICE_LATENCY.md). Pool ishlamasa — StreamingTranscriber o'zi ulanadi.
    """

    def __init__(self, client: Any, model: str, config_factory: Callable[[], Any], max_age_s: float = 480.0):
        self.client, self.model, self.config_factory, self.max_age_s = client, model, config_factory, max_age_s
        self.loop = asyncio.new_event_loop()
        self._ready: tuple[Any, Any, float] | None = None
        self._filling = False
        self.error = ""
        self.hits = self.misses = 0
        self._thread = threading.Thread(target=self.loop.run_forever, name="live-stt-pool", daemon=True)
        self._thread.start()
        self.refill()

    def refill(self) -> None:
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._fill()))

    async def _fill(self) -> None:
        if self._ready is not None or self._filling:
            return
        self._filling = True
        try:
            ctx = self.client.aio.live.connect(model=self.model, config=self.config_factory())
            session = await asyncio.wait_for(ctx.__aenter__(), timeout=8)
            self._ready = (ctx, session, time.monotonic())
            self.error = ""
        except Exception as e:  # noqa: BLE001 — keyingi buyruq o'zi ulanadi
            self.error = redact(f"{e.__class__.__name__}: {e}")[:160]
        finally:
            self._filling = False

    async def take(self) -> tuple[Any, Any] | None:
        """Tayyor sessiya (bo'lsa) — va darhol keyingisini fonda ochish."""
        r, self._ready = self._ready, None
        asyncio.ensure_future(self._fill())
        if r is None:
            self.misses += 1
            return None
        ctx, session, opened = r
        if time.monotonic() - opened > self.max_age_s:   # eskirgan — yopib, o'zi ulanadi
            self.misses += 1
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            return None
        self.hits += 1
        return ctx, session

    def run(self, coro: Any, timeout: float | None = None) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def info(self) -> dict[str, Any]:
        return {"ready": self._ready is not None, "hits": self.hits, "misses": self.misses, "error": self.error}

    def close(self) -> None:
        async def _close():
            if self._ready is not None:
                try:
                    await self._ready[0].__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
                self._ready = None
        try:
            self.run(_close(), timeout=3)
        except Exception:  # noqa: BLE001
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


def stream_config(vocabulary: list[str] | None = None) -> Any:
    from google.genai import types

    return types.LiveConnectConfig(response_modalities=["TEXT"], input_audio_transcription=types.AudioTranscriptionConfig(
        language_codes=BCP47, custom_vocabulary=(vocabulary or [])[:1000] or None))


class StreamingTranscriber:
    """Bitta buyruq uchun oqimli aniqlash. `run(stop)` — bloklovchi (alohida ipda chaqiriladi)."""

    def __init__(self, api_key: str, model: str, vocabulary: list[str] | None = None, client: Any = None,
                 source_factory: Callable[[], Any] = MicSource, on_partial: Callable[[str], None] | None = None,
                 on_level: Callable[[float], None] | None = None, final_grace_s: float = 2.0,
                 connect_timeout_s: float = 6.0, max_seconds: float = 30.0, endpointer: Endpointer | None = None,
                 auto: bool = True, pool: LiveSTTPool | None = None):
        self.model = model
        self.vocabulary = (vocabulary or [])[:1000]
        self.source_factory, self.on_partial, self.on_level = source_factory, on_partial, on_level
        self.final_grace_s, self.connect_timeout_s, self.max_seconds = final_grace_s, connect_timeout_s, max_seconds
        # auto: gap tugaganini o'zi sezadi (oqimda yakuniy matn tez keladi — qisqaroq jimlik); aks holda faqat tugma
        self.endpointer = (endpointer or Endpointer(silence_s=0.6)) if auto else None
        self.pool = pool
        if client is None and pool is not None:
            client = pool.client   # ulanishni qayta ishlatish: bitta mijoz
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version="v1beta"))
        self._client = client

    def run(self, stop: threading.Event) -> StreamResult:
        res = StreamResult(model=self.model)
        chunks: list[bytes] = []
        q: queue.Queue[bytes] = queue.Queue()
        t0 = time.perf_counter()
        speech_end = threading.Event()

        def ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        def on_chunk(b: bytes) -> None:
            chunks.append(b)
            q.put(b)
            pcm = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(pcm * pcm))) if pcm.size else 0.0
            if self.on_level is not None:
                try:
                    self.on_level(min(1.0, rms * 12))
                except Exception:  # noqa: BLE001
                    pass
            if self.endpointer is not None and not speech_end.is_set() and self.endpointer.feed(rms, len(pcm) / SAMPLE_RATE):
                res.marks.setdefault("speech_end", ms())
                speech_end.set()

        src = self.source_factory()
        try:
            src.start(on_chunk)
        except Exception as e:  # noqa: BLE001 — mikrofon ruxsati / qurilma
            res.finalized_by, res.error = "error", f"mic: {redact(str(e))[:160]}"
            return res
        try:
            if self.pool is not None:
                self.pool.run(self._session(q, stop, speech_end, res, ms))   # doimiy loop — oldindan ochilgan sessiya
            else:
                asyncio.run(self._session(q, stop, speech_end, res, ms))
        except Exception as e:  # noqa: BLE001
            from ..providers.gemini_provider import classify_error

            res.finalized_by, res.error = "error", str(classify_error(e, "Gemini Live STT"))
        finally:
            src.stop()
            if chunks:
                res.audio = np.frombuffer(b"".join(chunks), dtype="<i2").astype(np.float32) / 32768.0
        if res.finalized_by != "error" and not res.text.strip():
            res.finalized_by = "empty"
            res.reason = res.reason or ("no_speech" if self.endpointer is not None and self.endpointer.reason == "no_speech"
                                        else "no_transcript")
        return res

    def _config(self) -> Any:
        return stream_config(self.vocabulary)

    async def _session(self, q: queue.Queue, stop: threading.Event, speech_end: threading.Event, res: StreamResult,
                       ms: Callable[[], int]) -> None:
        from google.genai import types

        finals: list[str] = []
        interim = ""
        got_final = asyncio.Event()
        loop = asyncio.get_running_loop()
        pre = await self.pool.take() if self.pool is not None else None
        if pre is not None:
            connect, session = pre
            res.marks["pooled"] = 1          # oldindan ochilgan sessiya — ulanish kutilmadi
        else:
            connect = self._client.aio.live.connect(model=self.model, config=self._config())
            session = await asyncio.wait_for(connect.__aenter__(), timeout=self.connect_timeout_s)
        res.marks["connected"] = ms()
        try:
            async def sender() -> None:
                while not stop.is_set():
                    try:
                        b = await loop.run_in_executor(None, q.get, True, 0.1)
                    except queue.Empty:
                        continue
                    await session.send_realtime_input(audio=types.Blob(data=b, mime_type=f"audio/pcm;rate={SAMPLE_RATE}"))

            async def receiver() -> None:
                nonlocal interim
                while not stop.is_set():
                    async for m in session.receive():
                        sc = getattr(m, "server_content", None)
                        if sc is None:
                            continue
                        it = getattr(sc, "interim_input_transcription", None)
                        if it is not None and getattr(it, "text", None):
                            interim = it.text
                            res.marks.setdefault("first_partial", ms())
                            if self.on_partial is not None:
                                self.on_partial(("".join(finals) + " " + interim).strip())
                        ft = getattr(sc, "input_transcription", None)
                        if ft is not None and getattr(ft, "text", None):
                            finals.append(ft.text)
                            interim = ""
                            res.marks["final"] = ms()
                            res.marks.setdefault("first_partial", res.marks["final"])
                            got_final.set()
                            if self.on_partial is not None:
                                self.on_partial("".join(finals).strip())

            tasks = [asyncio.ensure_future(sender()), asyncio.ensure_future(receiver())]
            deadline = time.monotonic() + self.max_seconds

            def failed() -> BaseException | None:
                return next((t.exception() for t in tasks if t.done() and not t.cancelled() and t.exception()), None)

            try:
                while not stop.is_set() and not speech_end.is_set() and time.monotonic() < deadline:
                    if failed():
                        raise failed()   # type: ignore[misc]
                    await asyncio.sleep(0.03)
                no_speech = self.endpointer is not None and self.endpointer.reason == "no_speech"
                if not no_speech:
                    # Gap tugadi (VAD yoki tugma): yakuniy matnni qisqa kutamiz; oraliq bo'lak qolmasa — darhol
                    res.marks.setdefault("speech_end", ms())
                    waited = time.monotonic()
                    while time.monotonic() - waited < self.final_grace_s:
                        if failed():
                            raise failed()   # type: ignore[misc]
                        if got_final.is_set() and not interim:
                            break
                        await asyncio.sleep(0.03)
            finally:
                for t in tasks:
                    t.cancel()
        finally:
            try:
                await connect.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        text = "".join(finals).strip()
        if interim:
            text = (text + " " + interim).strip()
            # Server yakuniy matni kutish oralig'ida kelmadi — oraliq matn MAHALLIY yakunlandi (buyruq bajarilmaydi,
            # foydalanuvchi tasdiqlaydi)
            res.finalized_by = "local"
            res.reason = "no_server_final_within_grace" + ("_after_vad" if self.endpointer is not None else "_after_stop")
        elif text:
            res.finalized_by = "server"
            res.reason = "server_final"
        res.text = text
        res.marks.setdefault("final", ms())
