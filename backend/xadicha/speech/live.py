"""Gemini Live — real vaqtli ikki tomonlama ovozli suhbat (alohida quyi tizim).

Haqiqiy oqim: mikrofon (16 kHz, 16-bit PCM) → WebSocket (`client.aio.live.connect`) → model ovozi (24 kHz PCM)
→ karnay. Oddiy HTTP so'rovlar bilan "taqlid" qilinmaydi.

  * VAD — server tomonida (automatic_activity_detection); barge-in: server `interrupted` yuborsa, ijro darhol
    to'xtatiladi va navbat tozalanadi.
  * Kirish/chiqish transkripsiyasi — interfeysda jonli matn.
  * Sessiya: `go_away` yoki uzilishda `session_resumption` handle bilan qayta ulanish (cheklangan urinish).
  * Desktop amallari: model faqat `run_xadicha_command(instruction)` funksiyasini chaqira oladi — u mavjud agentga
    (router, xavfsizlik siyosati, tasdiq, registry) beriladi. Gemini hech qachon shell buyrug'ini bajarmaydi.

Eslatma: macOS'da `sounddevice` oqimlarida aks-sado so'ndirish (AEC) yo'q — karnaydan chiqqan ovoz mikrofonga
tushib, modelni o'zini o'zi to'xtatishi mumkin. Barge-in uchun quloqchin tavsiya etiladi.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from ..redaction import redact

log = logging.getLogger("xadicha")

IN_RATE, OUT_RATE = 16_000, 24_000
CHUNK_MS = 32
TOOL_NAME = "run_xadicha_command"

SYSTEM = (
    "You are XADICHA, a desktop voice assistant on the user's computer. You were created by Shohrux Shermirzayev; "
    "your name is XADICHA because he named you after his daughters — if asked why you are called XADICHA, say exactly "
    "that (in Uzbek: 'Meni yaratuvchim Shohrux Shermirzayev qizlarining nomidan andoza olib nomlagan, shuning uchun "
    "mening ismim Xadicha.'). Reply briefly and naturally in the language "
    "the user speaks (Uzbek in Latin script by default; Russian and English are also supported; the user may mix "
    "languages). Uzbek speech can sound similar to Turkish, Kazakh or Azerbaijani — the user never speaks those: "
    "treat such speech as Uzbek and always reply in Uzbek. For ANY request to control the computer — open or close apps, websites or files, find files, change "
    "volume or brightness, type text, search the web, describe the screen — call the function "
    f"`{TOOL_NAME}` with the user's request as `instruction`, in the user's own words (Uzbek requests in Uzbek Latin "
    "orthography, e.g. 'Safari ni och'). Never claim an action was done "
    "unless the function result says it succeeded; if it reports failure or a pending confirmation, say so honestly."
)


class SoundDeviceIO:
    """Mikrofon va karnay (sounddevice). Ijro navbati barge-in paytida bir zumda tozalanadi."""

    def __init__(self, device: Any = None):
        self.device = device
        self._in = self._out = None
        self._buf = bytearray()
        self._lock = threading.Lock()

    def start(self, on_chunk: Callable[[bytes], None]) -> None:
        import sounddevice as sd

        def mic(indata, frames, t, status):  # noqa: ARG001
            on_chunk(bytes(indata))

        def spk(outdata, frames, t, status):  # noqa: ARG001
            need = frames * 2
            with self._lock:
                chunk = bytes(self._buf[:need])
                del self._buf[:need]
            outdata[: len(chunk)] = chunk
            if len(chunk) < need:
                outdata[len(chunk):] = b"\x00" * (need - len(chunk))

        self._in = sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", device=self.device,
                                     blocksize=IN_RATE * CHUNK_MS // 1000, callback=mic)
        self._out = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", callback=spk)
        self._in.start()
        self._out.start()

    def play(self, pcm: bytes) -> None:
        with self._lock:
            self._buf.extend(pcm)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    @property
    def playing(self) -> bool:
        with self._lock:
            return len(self._buf) > 0

    def stop(self) -> None:
        for s in (self._in, self._out):
            try:
                if s is not None:
                    s.stop()
                    s.close()
            except Exception:  # noqa: BLE001
                pass
        self._in = self._out = None
        self.clear()


class LiveSession:
    """Bitta Live suhbat. Holat: idle | connecting | listening | thinking | speaking | interrupted |
    reconnecting | error | closed. Hodisalar `emit` orqali (WebSocket'ga) yuboriladi."""

    def __init__(self, api_key: str, model: str, emit: Callable[[dict[str, Any]], None],
                 run_command: Callable[[str], dict[str, Any]] | None = None, voice: str = "",
                 vocabulary: list[str] | None = None, audio_factory: Callable[[], Any] = SoundDeviceIO,
                 client: Any = None, max_reconnects: int = 3, backoff_s: float = 1.0):
        if not api_key and client is None:
            from ..providers.base import ProviderError

            raise ProviderError("GEMINI_API_KEY o'rnatilmagan — Gemini Live ishlamaydi.", kind="config")
        self.model, self.voice = model, voice
        self.vocabulary = (vocabulary or [])[:1000]
        self.emit, self.run_command = emit, run_command
        self.audio_factory = audio_factory
        self.max_reconnects, self.backoff_s = max_reconnects, backoff_s
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version="v1beta"))
        self._client = client
        self.state = "idle"
        self.error = ""
        self.handle: str | None = None          # session_resumption handle
        self.reconnects = 0
        self.turns = 0
        self.first_audio_ms: int | None = None  # oxirgi navbatda: foydalanuvchi to'xtagandan birinchi ovozgacha
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mic: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._audio = None
        self._user_text = ""
        self._model_text = ""
        self._last_voice: float | None = None   # mikrofonda oxirgi marta nutq eshitilgan payt (monotonic)
        self._last_level = 0.0

    # --- holat ---
    def _set(self, state: str, **extra: Any) -> None:
        self.state = state
        self.emit({"type": "live_state", "state": state, **extra})

    def info(self) -> dict[str, Any]:
        return {"active": self.active, "state": self.state, "model": self.model, "error": self.error,
                "reconnects": self.reconnects, "turns": self.turns, "resumable": bool(self.handle),
                "first_audio_ms": self.first_audio_ms}

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # --- boshqaruv ---
    def start(self) -> None:
        if self.active:
            return
        self._stop.clear()
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="gemini-live", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread is not None:
            self._thread.join(timeout)
        if self._audio is not None:
            self._audio.stop()
            self._audio = None
        if self.state != "error":
            self._set("closed")

    # --- ichki ---
    def _on_mic(self, chunk: bytes) -> None:
        if self._stop.is_set():
            return
        try:
            self._mic.put_nowait(chunk)
        except queue.Full:
            pass   # tarmoq sekin — eski bo'lak tashlanadi (kechikish to'planmasin)
        now = time.monotonic()
        pcm = np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768.0
        level = float(min(1.0, np.sqrt(np.mean(pcm * pcm)) * 12)) if pcm.size else 0.0
        if level >= 0.05:
            self._last_voice = now
        if now - self._last_level >= 0.066:
            self._last_level = now
            self.emit({"type": "mic_level", "level": round(level, 3), "source": "live"})

    def _config(self) -> Any:
        from google.genai import types

        cfg: dict[str, Any] = dict(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM,
            # Faqat uch til: o'zbek nutqi turk/qozoq deb yozilmasin
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=["uz-UZ", "ru-RU", "en-US"], custom_vocabulary=self.vocabulary or None),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(automatic_activity_detection=types.AutomaticActivityDetection(
                silence_duration_ms=700, prefix_padding_ms=200)),
            session_resumption=types.SessionResumptionConfig(handle=self.handle),
            context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
            tools=[types.Tool(function_declarations=[types.FunctionDeclaration(
                name=TOOL_NAME,
                description="Run a desktop command through XADICHA's safe action system (apps, files, volume, "
                            "brightness, web search, typing, screen). Returns the real result.",
                parameters={"type": "object", "properties": {"instruction": {
                    "type": "string", "description": "The user's request in their own words"}},
                    "required": ["instruction"]})])],
        )
        if self.voice:
            cfg["speech_config"] = types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)))
        return types.LiveConnectConfig(**cfg)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()
            self._loop = None

    async def _main(self) -> None:
        from ..providers.gemini_provider import classify_error

        try:
            self._audio = self.audio_factory()
            self._audio.start(self._on_mic)
        except Exception as e:  # noqa: BLE001 — mikrofon ruxsati / qurilma yo'q
            self.error = f"Mikrofon ochilmadi: {redact(str(e))[:160]}"
            self._set("error", error=self.error)
            return
        attempt = 0
        while not self._stop.is_set():
            self._set("connecting" if attempt == 0 and not self.handle else "reconnecting")
            try:
                async with self._client.aio.live.connect(model=self.model, config=self._config()) as session:
                    attempt = 0
                    self._set("listening")
                    reason = await self._session(session)
                if reason == "stopped":
                    break
                self.reconnects += 1          # go_away yoki server yopdi — handle bilan davom etamiz
            except Exception as e:  # noqa: BLE001
                err = classify_error(e, "Gemini Live")
                self.error = str(err)
                if err.kind in ("auth", "config") or attempt >= self.max_reconnects:
                    log.warning("Gemini Live to'xtadi (%s): %s", err.kind, self.error)
                    self._set("error", error=self.error, kind=err.kind)
                    break
                attempt += 1
                self.reconnects += 1
                log.info("Gemini Live qayta ulanmoqda (%d/%d): %s", attempt, self.max_reconnects, self.error)
                await asyncio.sleep(self.backoff_s * attempt)
        if self._audio is not None:
            self._audio.stop()
            self._audio = None

    async def _session(self, session: Any) -> str:
        sender = asyncio.ensure_future(self._send_loop(session))
        try:
            return await self._recv_loop(session)
        finally:
            sender.cancel()

    async def _send_loop(self, session: Any) -> None:
        from google.genai import types

        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                chunk = await loop.run_in_executor(None, self._mic.get, True, 0.2)
            except queue.Empty:
                continue
            await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={IN_RATE}"))

    async def _recv_loop(self, session: Any) -> str:
        while not self._stop.is_set():
            got = 0
            async for msg in session.receive():   # bitta model navbati (turn_complete'gacha)
                got += 1
                if self._stop.is_set():
                    return "stopped"
                if await self._handle(session, msg) == "go_away":
                    return "go_away"
            if got == 0:
                return "stopped" if self._stop.is_set() else "closed"   # server ulanishni yopdi — qayta ulanamiz
        return "stopped"

    async def _handle(self, session: Any, msg: Any) -> str | None:
        upd = getattr(msg, "session_resumption_update", None)
        if upd is not None and getattr(upd, "resumable", False) and getattr(upd, "new_handle", None):
            self.handle = upd.new_handle
        if getattr(msg, "go_away", None) is not None:
            log.info("Gemini Live: go_away (%s) — qayta ulanish", getattr(msg.go_away, "time_left", ""))
            return "go_away"
        if getattr(msg, "tool_call", None) is not None:
            await self._tool_call(session, msg.tool_call)
        sc = getattr(msg, "server_content", None)
        if sc is None:
            return None
        if getattr(sc, "interrupted", False):
            if self._audio is not None:
                self._audio.clear()          # barge-in: ijro darhol to'xtaydi
            self._model_text = ""
            self._set("interrupted")
            self._set("listening")
        it = getattr(sc, "input_transcription", None)
        if it is not None and getattr(it, "text", None):
            self._user_text += it.text
            self.emit({"type": "live_transcript", "role": "user", "text": self._user_text.strip(), "final": False})
        ot = getattr(sc, "output_transcription", None)
        if ot is not None and getattr(ot, "text", None):
            self._model_text += ot.text
            self.emit({"type": "live_transcript", "role": "assistant", "text": self._model_text.strip(), "final": False})
        turn = getattr(sc, "model_turn", None)
        for part in (getattr(turn, "parts", None) or []):
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                if self.state != "speaking":
                    if self._last_voice is not None:
                        # nutq tugashidan birinchi javob ovozigacha (mijoz tomonida o'lchanadi)
                        self.first_audio_ms = int((time.monotonic() - self._last_voice) * 1000)
                    self._set("speaking")
                if self._audio is not None:
                    self._audio.play(data)
        if getattr(sc, "turn_complete", False):
            self.turns += 1
            if self._user_text.strip() or self._model_text.strip():
                self.emit({"type": "live_turn", "user": self._user_text.strip(), "assistant": self._model_text.strip(),
                           "first_audio_ms": self.first_audio_ms})
            self._user_text = self._model_text = ""
            self._set("listening")
        return None

    async def _tool_call(self, session: Any, tool_call: Any) -> None:
        from google.genai import types

        responses = []
        for fc in (getattr(tool_call, "function_calls", None) or []):
            args = dict(getattr(fc, "args", None) or {})
            if fc.name != TOOL_NAME or not str(args.get("instruction", "")).strip():
                result = {"status": "rejected", "result": "Noma'lum funksiya yoki bo'sh buyruq — bajarilmadi."}
            elif self.run_command is None:
                result = {"status": "unavailable", "result": "Desktop buyruqlari hozir mavjud emas."}
            else:
                self._set("thinking", instruction=str(args["instruction"])[:200])
                loop = asyncio.get_running_loop()
                try:
                    result = await loop.run_in_executor(None, self.run_command, str(args["instruction"]))
                except Exception as e:  # noqa: BLE001
                    result = {"status": "failed", "result": redact(f"{e.__class__.__name__}: {e}")[:200]}
            responses.append(types.FunctionResponse(id=getattr(fc, "id", None), name=fc.name, response=result))
        if responses:
            await session.send_tool_response(function_responses=responses)
