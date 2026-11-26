"""Oqimli buyruq STT, kechikish belgilari, tezkor router, TTS bo'laklari, adaptiv timeout.

SIMULYATSIYA: Live Transcription sessiyasi va mikrofon soxta (tarmoq yo'q). Haqiqiy o'lchovlar:
`python scripts/voice_latency_bench.py` (docs/VOICE_LATENCY.md).
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import ScriptedProvider, api_client
from google.genai import types
from test_gemini import FAKE_KEY, Clock, api_error, response

from xadicha.adapters.base import DryRunAdapter
from xadicha.providers.gemini_provider import GeminiProvider
from xadicha.router import route
from xadicha.service import XadichaService
from xadicha.speech.stream import StreamingTranscriber
from xadicha.speech.tts import speech_chunks

LOUD = (np.full(1024, 6000, dtype="<i2")).tobytes()      # 64 ms "nutq"
QUIET = (np.zeros(1024, dtype="<i2")).tobytes()          # 64 ms jimlik


def M(**kw):
    return types.LiveServerMessage.model_validate(kw)


class FakeSource:
    """Mikrofon: nutq bo'laklari, keyin jimlik (real vaqtdan tezroq)."""

    def __init__(self, speech_chunks_n=10, silence_n=40, delay=0.005):
        self.seq = [LOUD] * speech_chunks_n + [QUIET] * silence_n
        self.delay, self._stop = delay, threading.Event()

    def start(self, on_chunk):
        def run():
            for _ in range(5):          # kalibrlash uchun boshlang'ich jimlik
                on_chunk(QUIET)
            for b in self.seq:
                if self._stop.is_set():
                    return
                on_chunk(b)
                time.sleep(self.delay)
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self._stop.set()


class FakeStreamSession:
    def __init__(self, script):
        self.script, self.sent = list(script), 0

    async def send_realtime_input(self, **kw):
        self.sent += 1

    def receive(self):
        async def gen():
            if not self.script:
                await asyncio.sleep(0.05)
                return
            for delay, msg in self.script.pop(0):
                await asyncio.sleep(delay)
                yield msg
        return gen()


class FakeLiveClient:
    def __init__(self, script=None, fail=None):
        self.script, self.fail, self.configs = script or [], fail, []
        outer = self

        class Live:
            def connect(self, model, config):
                outer.configs.append(config)

                class Ctx:
                    async def __aenter__(self):
                        if outer.fail:
                            raise outer.fail
                        outer.session = FakeStreamSession(outer.script)
                        return outer.session

                    async def __aexit__(self, *a):
                        return False
                return Ctx()

        self.aio = type("Aio", (), {"live": Live()})()


def interim(t):
    return M(server_content={"interim_input_transcription": {"text": t}})


def final(t):
    return M(server_content={"input_transcription": {"text": t}})


def transcriber(script=None, fail=None, **kw):
    partials = []
    st = StreamingTranscriber("", "gemini-3.5-transcribe-live", vocabulary=["Xadicha"], client=FakeLiveClient(script, fail),
                              source_factory=kw.pop("source", FakeSource), on_partial=partials.append,
                              final_grace_s=kw.pop("grace", 0.6), **kw)
    return st, partials


# ---------- oqimli STT ----------

def test_interim_then_server_final():
    st, partials = transcriber([[(0.02, interim("Safari")), (0.02, interim("Safari ni")), (0.05, final("Safari ni och."))]])
    r = st.run(threading.Event())
    assert r.text == "Safari ni och." and r.finalized_by == "server"
    assert partials[0] == "Safari" and partials[-1] == "Safari ni och."
    assert r.marks["first_partial"] <= r.marks["final"] and "connected" in r.marks
    cfg = st._client.configs[0]
    assert cfg.response_modalities == ["TEXT"] and cfg.input_audio_transcription.language_codes == ["uz-UZ", "ru-RU", "en-US"]
    assert r.audio.size > 0                                   # bufer zaxira uchun xotirada


def test_late_final_uses_last_interim_and_marks_it():
    st, _ = transcriber([[(0.02, interim("Telegramni ochib qo'y"))]], grace=0.3)
    r = st.run(threading.Event())
    assert r.text == "Telegramni ochib qo'y" and r.finalized_by == "interim"   # yashirilmaydi


def test_connect_failure_returns_buffered_audio_for_fallback():
    st, _ = transcriber(fail=ConnectionError("internet yo'q"))
    r = st.run(threading.Event())
    assert r.finalized_by == "error" and "tarmoq" in r.error and r.audio.size > 0


def test_auth_error_is_classified():
    from google.genai import errors

    bad = errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT",
                                              "details": [{"reason": "API_KEY_INVALID"}]}})
    st, _ = transcriber(fail=bad)
    r = st.run(threading.Event())
    assert r.finalized_by == "error" and "API kaliti" in r.error


def test_no_speech_ends_quickly_with_empty_result():
    st, _ = transcriber([], source=lambda: FakeSource(speech_chunks_n=0, silence_n=200, delay=0.001))
    st.endpointer.no_speech_s = 0.5
    r = st.run(threading.Event())
    assert r.text == "" and r.finalized_by == "empty"


def test_manual_mode_does_not_autostop():
    st, _ = transcriber([[(0.01, final("ovozni ko'tar"))]], auto=False)
    stop = threading.Event()
    threading.Timer(0.4, stop.set).start()
    t0 = time.time()
    r = st.run(stop)
    assert time.time() - t0 >= 0.35 and r.text == "ovozni ko'tar"


# ---------- service: oqimli yo'l, hodisalar, kechikish ----------

class FakeStreamer:
    def __init__(self, text="ovozni ko'tar", finalized_by="server", error="", **kw):
        self.kw, self.text, self.finalized_by, self.error = kw, text, finalized_by, error

    def run(self, stop):
        from xadicha.speech.stream import StreamResult

        if self.kw.get("on_partial"):
            self.kw["on_partial"]("ovozni")
            self.kw["on_partial"](self.text)
        return StreamResult(text=self.text if not self.error else "", finalized_by=self.finalized_by, error=self.error,
                            audio=np.zeros(16000, dtype=np.float32), model="gemini-3.5-transcribe-live",
                            marks={"connected": 400, "first_partial": 700, "speech_end": 1500, "final": 2100})


def stream_svc(cfg, storage, **fs):
    cfg.fast_path, cfg.gemini_api_key, cfg.stt_provider = True, FAKE_KEY, "auto"
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc.stream_factory = lambda **kw: FakeStreamer(**fs, **kw)
    events = []
    svc.subscribe(events.append)
    return svc, events, api_client(svc)


def wait(cond, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_streaming_voice_command_runs_with_partials_and_latency(cfg, storage):
    svc, events, client = stream_svc(cfg, storage)
    client.post("/api/listen/start?language=uz&auto=true")
    assert wait(lambda: any(e["type"] == "voice_latency" for e in events))
    parts = [e["text"] for e in events if e["type"] == "stt_partial"]
    assert parts and parts[-1] == "ovozni ko'tar"
    tr = next(e for e in events if e["type"] == "transcript")
    assert tr["stt_provider"] == "gemini-live" and tr["finalized_by"] == "server" and tr["language"] == "uz"
    lat = next(e for e in events if e["type"] == "voice_latency")
    assert lat["ttf_partial"] == 700 and lat["ttf_final"] == 2100 and lat["stt"] == "gemini-live"
    assert lat["tt_first_action"] is not None   # soxta oqim belgilari sintetik — tartib haqiqiy sinovda tekshiriladi
    assert lat["tt_response_text"] >= lat["tt_first_action"]
    task = client.get("/api/tasks").json()[0]
    assert task["data"]["latency"]["ttf_final"] == 2100 and task["steps"][0]["action"]["control"] == "volume_up"


def test_stream_failure_falls_back_to_unary_with_same_audio(cfg, storage):
    from test_stt_providers import FakeWhisper

    svc, events, client = stream_svc(cfg, storage, finalized_by="error", error="Gemini Live STT: tarmoq xatosi")
    svc.listener = FakeWhisper(text="ovozni ko'tar")
    svc.stt.whisper = svc.listener
    svc.stt.gemini = None
    client.post("/api/listen/start?language=uz&auto=true")
    assert wait(lambda: any(e["type"] == "task_finished" for e in events))
    tr = next(e for e in events if e["type"] == "transcript")
    assert tr["stt_provider"].startswith("whisper")
    trace = client.get("/api/tasks").json()[0]["trace"]
    assert any(s["stage"] == "stt_stream" and not s["ok"] for s in trace)
    assert svc.stream_available() is False                      # 120 s davomida qayta urinmaydi


def test_stream_not_used_offline_or_whisper_mode(cfg, storage):
    svc, _, client = stream_svc(cfg, storage)
    client.put("/api/settings", json={"offline_mode": True})
    assert svc.stream_available() is False
    client.put("/api/settings", json={"offline_mode": False, "stt_provider": "whisper"})
    assert svc.stream_available() is False


# ---------- tezkor router ----------

@pytest.mark.parametrize("text,expect", [
    ("Ovoz balandligini kamaytir", "volume_down"),        # avval xato: volume_up
    ("Ovoz balandligini oshir", "volume_up"),
    ("Screenshot ol", "screenshot"), ("Ekran rasmini ol", "screenshot"), ("Скриншот сделай", "screenshot"),
    ("Take a screenshot", "screenshot"), ("Ekran yorqinligini oshir", "brightness_up"),
])
def test_fast_system_commands(text, expect):
    r = route(text, "uz")
    assert r.path == "fast" and r.actions[0].control == expect


@pytest.mark.parametrize("text,query", [
    ("Oxirgi yuklangan faylni top", ":latest-download"),
    ("Kecha yuklab olgan PDF faylimni top.", ":latest-download:pdf"),
    ("Find the last downloaded file", ":latest-download"),
    ("Последний скачанный файл найди", ":latest-download"),
])
def test_latest_download_route(text, query):
    r = route(text, "uz")
    assert r.path == "tool" and r.actions[0].type == "find_file" and r.actions[0].text == query


def test_latest_downloads_sorted_files_only(tmp_path, monkeypatch):
    from xadicha.tools import files

    home = tmp_path
    dl = home / "Downloads"
    dl.mkdir()
    for i, name in enumerate(["a.pdf", "b.png", "c.pdf"]):
        f = dl / name
        f.write_text("x")
        import os
        os.utime(f, (1000 + i, 1000 + i))
    (dl / "folder").mkdir()
    monkeypatch.setattr(files.Path, "home", staticmethod(lambda: home))
    assert [p.name for p in files.find_files(":latest-download", home)] == ["c.pdf", "b.png", "a.pdf"]
    assert [p.name for p in files.find_files(":latest-download:pdf", home)] == ["c.pdf", "a.pdf"]


def test_screenshot_is_low_risk_and_allowed():
    from xadicha import safety
    from xadicha.models import Action, RiskLevel

    a = Action(type="system", control="screenshot")
    assert safety.final_risk(a, RiskLevel.low, Path.home()) == RiskLevel.low
    assert safety.blocked_reason(a, Path.home()) is None


# ---------- TTS bo'laklari ----------

def test_speech_chunks_first_is_short():
    parts = speech_chunks("Samarqand qadimiy shahar. U Buyuk ipak yo'lida joylashgan. Masjidlari mashhur. Boqiy shahar.")
    assert len(parts) >= 2 and parts[0] == "Samarqand qadimiy shahar." and "Boqiy" in parts[-1]
    assert speech_chunks("Bajarildi.") == ["Bajarildi."]


# ---------- adaptiv timeout ----------

def test_recently_failed_model_gets_short_timeout_and_growing_cooldown():
    from test_gemini import FakeClient

    clock = Clock()
    g = GeminiProvider(FAKE_KEY, "main", client=FakeClient([api_error(504, "x", "DEADLINE_EXCEEDED"),
                                                            response('{"reply": "lite"}'),
                                                            api_error(504, "x", "DEADLINE_EXCEEDED"),
                                                            response('{"reply": "lite2"}'),
                                                            response('{"reply": "main ok"}')]),
                       fallback_models=["lite"], clock=clock, retry_delay=0)
    g.complete("s", "u", None)
    clock.t += 121
    g.complete("s", "u", None)                                 # main qayta sinaladi — qisqa timeout bilan
    call = g._client.models.calls[2]
    assert call["model"] == "main" and call["config"].http_options.timeout == 5000
    assert g._down["main"][0] - clock.t >= 239                 # 2-yiqilish: cooldown ikki baravar
    clock.t += 241
    assert g.complete("s", "u", None) == '{"reply": "main ok"}' and "main" not in g._strikes


def test_empty_stream_with_speech_falls_back_to_buffered_audio(cfg, storage):
    from test_stt_providers import FakeWhisper

    class EmptyButSpeech(FakeStreamer):
        def run(self, stop):
            r = super().run(stop)
            r.text, r.finalized_by = "", "empty"
            r.audio = (0.2 * np.sin(np.linspace(0, 2000, 16000))).astype(np.float32)
            return r

    cfg.fast_path, cfg.gemini_api_key = True, FAKE_KEY
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc.stream_factory = lambda **kw: EmptyButSpeech(**kw)
    svc.listener = FakeWhisper(text="ovozni ko'tar")
    svc.stt.whisper, svc.stt.gemini = svc.listener, None
    events = []
    svc.subscribe(events.append)
    api_client(svc).post("/api/listen/start?language=uz&auto=true")
    assert wait(lambda: any(e["type"] == "transcript" for e in events))
    assert next(e for e in events if e["type"] == "transcript")["stt_provider"].startswith("whisper")
    assert svc.stream_available() is True        # bo'sh natija — ulanish xatosi emas, oqim o'chirilmaydi
