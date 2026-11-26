"""Gemini Live quyi tizimi — sessiya hayot sikli, barge-in, qayta ulanish, desktop buyruqlari.

SIMULYATSIYA: WebSocket sessiyasi va audio qurilmalar soxta (tarmoq, mikrofon, karnay yo'q); server xabarlari rasmiy
SDK turidan (types.LiveServerMessage) quriladi. Haqiqiy sinov: `python scripts/gemini_live_smoke.py`.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from conftest import ScriptedProvider, api_client
from google.genai import errors, types

from xadicha.adapters.base import DryRunAdapter
from xadicha.service import XadichaService
from xadicha.speech.live import TOOL_NAME, LiveSession


def M(**kw) -> types.LiveServerMessage:
    return types.LiveServerMessage.model_validate(kw)


AUDIO = {"inline_data": {"data": b"\x01\x00" * 480, "mime_type": "audio/pcm;rate=24000"}}


class FakeAudio:
    def __init__(self, fail=False):
        self.fail, self.played, self.cleared, self.stopped = fail, [], 0, False

    def start(self, on_chunk):
        if self.fail:
            raise OSError("Input device not available")
        for _ in range(3):
            on_chunk(b"\x00\x20" * 512)   # baland bo'lak (nutq) — kechikish o'lchovi uchun

    def play(self, pcm):
        self.played.append(pcm)

    def clear(self):
        self.cleared += 1

    def stop(self):
        self.stopped = True


class FakeSession:
    def __init__(self, turns, stop: threading.Event):
        self.turns, self.stop_ev = list(turns), stop
        self.sent: list[dict] = []
        self.tool_responses: list = []

    async def send_realtime_input(self, **kw):
        self.sent.append(kw)

    async def send_tool_response(self, function_responses):
        self.tool_responses.append(function_responses)

    def receive(self):
        async def gen():
            if not self.turns:
                while not self.stop_ev.is_set():   # ssenariy tugadi — foydalanuvchi to'xtatguncha jim
                    await asyncio.sleep(0.01)
                return
            for m in self.turns.pop(0):
                yield m
        return gen()


class FakeLive:
    def __init__(self, sessions, errors_=None):
        self.sessions, self.errors = list(sessions), list(errors_ or [])
        self.configs: list = []
        self.stop_ev = threading.Event()

    def connect(self, model, config):
        outer = self

        class Ctx:
            async def __aenter__(self):
                outer.configs.append(config)
                if outer.errors:
                    raise outer.errors.pop(0)
                turns = outer.sessions.pop(0) if outer.sessions else []
                self.s = FakeSession(turns, outer.stop_ev)
                outer.last = self.s
                return self.s

            async def __aexit__(self, *a):
                return False

        return Ctx()


class FakeClient:
    def __init__(self, live):
        self.aio = type("Aio", (), {"live": live})()


def make(sessions, errors_=None, run_command=None, audio=None, **kw):
    live = FakeLive(sessions, errors_)
    events: list[dict] = []
    audio = audio or FakeAudio()
    s = LiveSession("", "gemini-3.8-live", events.append, run_command=run_command, client=FakeClient(live),
                    audio_factory=lambda: audio, backoff_s=0, **kw)
    return s, live, events, audio


def wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def finish(s, live):
    live.stop_ev.set()
    s.stop()


def states(events):
    return [e["state"] for e in events if e["type"] == "live_state"]


# ---------- oqim ----------

def test_streams_mic_audio_plays_model_audio_and_transcripts():
    turn = [M(server_content={"input_transcription": {"text": "Salom, "}}),
            M(server_content={"input_transcription": {"text": "qalaysan?"}}),
            M(server_content={"output_transcription": {"text": "Yaxshi, rahmat!"}, "model_turn": {"parts": [AUDIO]}}),
            M(server_content={"model_turn": {"parts": [AUDIO]}}),
            M(server_content={"turn_complete": True})]
    s, live, events, audio = make([[turn]])
    s.start()
    assert wait(lambda: any(e["type"] == "live_turn" for e in events))
    finish(s, live)
    sent = live.last.sent
    assert sent and sent[0]["audio"].mime_type == "audio/pcm;rate=16000" and len(sent[0]["audio"].data) == 1024
    assert len(audio.played) == 2
    t = next(e for e in events if e["type"] == "live_turn")
    assert t["user"] == "Salom, qalaysan?" and t["assistant"] == "Yaxshi, rahmat!"
    st = states(events)
    assert st[:2] == ["connecting", "listening"] and "speaking" in st and st[-1] == "closed"
    assert any(e["type"] == "mic_level" and e["source"] == "live" for e in events)
    cfg = live.configs[0]
    assert cfg.response_modalities == ["AUDIO"]
    assert cfg.input_audio_transcription.language_codes == ["uz-UZ", "ru-RU", "en-US"]
    assert cfg.realtime_input_config.automatic_activity_detection.silence_duration_ms == 700
    assert cfg.tools[0].function_declarations[0].name == TOOL_NAME
    assert s.turns == 1 and s.first_audio_ms is not None


def test_barge_in_interrupt_clears_playback_immediately():
    turn = [M(server_content={"model_turn": {"parts": [AUDIO]}}),
            M(server_content={"interrupted": True}),
            M(server_content={"turn_complete": True})]
    s, live, events, audio = make([[turn]])
    s.start()
    assert wait(lambda: "interrupted" in states(events))
    finish(s, live)
    assert audio.cleared >= 1 and states(events).index("interrupted") > states(events).index("speaking")


def test_resumption_handle_used_after_go_away():
    first = [[M(session_resumption_update={"new_handle": "h-123", "resumable": True}), M(go_away={"time_left": "5s"})]]
    s, live, events, _ = make([first, []])
    s.start()
    assert wait(lambda: len(live.configs) >= 2)
    finish(s, live)
    assert live.configs[0].session_resumption.handle is None
    assert live.configs[1].session_resumption.handle == "h-123"
    assert s.reconnects >= 1 and "reconnecting" in states(events)


# ---------- desktop buyruqlari ----------

def test_tool_call_goes_through_agent_and_result_is_returned():
    calls = []

    def run(instr):
        calls.append(instr)
        return {"status": "success", "result": "Safari ochildi."}

    turn = [M(tool_call={"function_calls": [{"id": "c1", "name": TOOL_NAME, "args": {"instruction": "Safari ni och"}}]}),
            M(server_content={"turn_complete": True})]
    s, live, events, _ = make([[turn]], run_command=run)
    s.start()
    assert wait(lambda: live.__dict__.get("last") is not None and live.last.tool_responses)
    finish(s, live)
    fr = live.last.tool_responses[0][0]
    assert calls == ["Safari ni och"] and fr.id == "c1" and fr.name == TOOL_NAME
    assert fr.response == {"status": "success", "result": "Safari ochildi."}
    assert "thinking" in states(events)


def test_unknown_function_is_rejected_and_nothing_runs():
    calls = []
    turn = [M(tool_call={"function_calls": [{"id": "x", "name": "shell", "args": {"cmd": "rm -rf ~"}}]})]
    s, live, _, _ = make([[turn]], run_command=lambda i: calls.append(i) or {"status": "success"})
    s.start()
    assert wait(lambda: live.__dict__.get("last") is not None and live.last.tool_responses)
    finish(s, live)
    assert calls == [] and live.last.tool_responses[0][0].response["status"] == "rejected"


# ---------- xatolar ----------

def test_invalid_key_stops_without_retry():
    bad = errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT",
                                              "details": [{"reason": "API_KEY_INVALID"}]}})
    s, live, events, audio = make([], errors_=[bad])
    s.start()
    assert wait(lambda: "error" in states(events))
    s.stop()
    assert len(live.configs) == 1 and "API kaliti" in s.error and audio.stopped
    assert next(e for e in events if e.get("state") == "error")["kind"] == "auth"


def test_network_errors_retry_limited_times():
    s, live, events, _ = make([], errors_=[ConnectionError("down")] * 10, max_reconnects=2)
    s.start()
    assert wait(lambda: "error" in states(events))
    s.stop()
    assert len(live.configs) == 3 and states(events).count("reconnecting") >= 2   # cheksiz urinish yo'q


def test_microphone_failure_is_reported():
    s, live, events, _ = make([], audio=FakeAudio(fail=True))
    s.start()
    assert wait(lambda: "error" in states(events))
    s.stop()
    assert "Mikrofon" in s.error and live.configs == []


# ---------- service va API ----------

def test_live_unavailable_without_key_returns_409(cfg, storage):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    client = api_client(svc)
    r = client.post("/api/live/start")
    assert r.status_code == 409 and "GEMINI_API_KEY" in r.json()["detail"]
    st = client.get("/api/status").json()["live"]
    assert st["available"] is False and st["active"] is False


def test_live_via_api_saves_turns_and_runs_commands_safely(cfg, storage):
    cfg.fast_path = True
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    turn = [M(server_content={"input_transcription": {"text": "Ovozni ko'tar"}}),
            M(tool_call={"function_calls": [{"id": "t1", "name": TOOL_NAME, "args": {"instruction": "ovozni ko'tar"}}]}),
            M(server_content={"output_transcription": {"text": "Ovoz ko'tarildi."}}),
            M(server_content={"turn_complete": True})]
    live = FakeLive([[turn]])
    sessions = []

    def factory(**kw):
        s = LiveSession("", "gemini-3.8-live", client=FakeClient(live), audio_factory=FakeAudio, backoff_s=0, **kw)
        sessions.append(s)
        return s

    svc.start_live(session_factory=factory)
    assert wait(lambda: any(t.role == "assistant" and "ko'tarildi" in t.text for t in svc.conversation.turns))
    resp = live.last.tool_responses[0][0].response
    assert resp["status"] == "success" and resp["steps"][0]["action"].startswith("Tizim")   # mavjud agent orqali
    assert svc.storage.list_turns(svc.conversation.session_id, 20)
    live.stop_ev.set()
    info = svc.stop_live()
    assert info["active"] is False and info["turns"] == 1


def test_live_command_reports_busy(cfg, storage):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc._run_lock.acquire()
    try:
        assert svc._live_command("Safari ni och")["status"] == "busy"
    finally:
        svc._run_lock.release()


def test_live_disabled_by_config(cfg, storage):
    cfg.gemini_api_key, cfg.live_enabled = "k" * 20, False
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    with pytest.raises(RuntimeError):
        svc.start_live()


# ---------- B2: aks-sado himoyasi ----------

class PlayingAudio(FakeAudio):
    playing = True


def test_mic_is_gated_while_xadicha_speaks_without_headphones():
    s, live, events, audio = make([], audio=PlayingAudio())
    s._audio = audio
    s._on_mic(b"\x00\x20" * 512)
    assert s.gated_chunks == 1 and s._mic.get_nowait() == b"\x00" * 1024   # aks-sado o'rniga jimlik (oqim tirik)


def test_barge_in_enabled_passes_mic_audio_through():
    s, live, events, audio = make([], audio=PlayingAudio(), barge_in=True)
    s._audio = audio
    s._on_mic(b"\x00\x20" * 512)
    assert s.gated_chunks == 0 and s._mic.get_nowait() == b"\x00\x20" * 512


def test_mic_open_again_after_echo_tail():
    s, live, events, audio = make([])
    s._audio = audio                                  # playing yo'q
    s._last_play = time.monotonic() - 1.0             # ijro 1 s oldin tugagan
    s._on_mic(b"\x00\x20" * 512)
    assert s.gated_chunks == 0
