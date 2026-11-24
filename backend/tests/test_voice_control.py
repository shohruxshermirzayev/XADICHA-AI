"""Ovoz/yorqinlik buyruqlari, gapirib bo'linganini sezish va avtomatik bajarish (SIMULYATSIYA).

Real macOS'da ovoz va yorqinlik o'zgarishi bu testlarda tekshirilmaydi (osascript soxtalashtirilgan).
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from conftest import ScriptedProvider, api_client

from xadicha import safety
from xadicha.adapters import macos as mac
from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent
from xadicha.models import Action, RiskLevel
from xadicha.providers.rule_based import parse_command
from xadicha.service import XadichaService
from xadicha.speech.stt import Endpointer, Transcript, is_hallucination

CASES = [
    ("Ovozini ko'tar", "uz", [("volume_up", None)]), ("ovozni oshir", "uz", [("volume_up", None)]),
    ("ovozni pasaytir", "uz", [("volume_down", None)]), ("ovozni o'chir", "uz", [("mute", None)]),
    ("ovozni yoq", "uz", [("unmute", None)]), ("ovozni 40 ga qo'y", "uz", [("volume_set", 40)]),
    ("yorug'likni oshir", "uz", [("brightness_up", None)]), ("ekran yorqinligini pasaytir", "uz", [("brightness_down", None)]),
    ("ekranni yorqinroq qil", "uz", [("brightness_up", None)]),
    ("ovozni ko'tar va yorug'likni oshir", "uz", [("volume_up", None), ("brightness_up", None)]),
    ("Овозни кўтар", "uz", [("volume_up", None)]), ("ёруғликни камайтир", "uz", [("brightness_down", None)]),
    ("сделай громче", "ru", [("volume_up", None)]), ("тише", "ru", [("volume_down", None)]),
    ("выключи звук", "ru", [("mute", None)]), ("громкость на 30", "ru", [("volume_set", 30)]),
    ("увеличь яркость", "ru", [("brightness_up", None)]), ("ярче", "ru", [("brightness_up", None)]),
    ("volume up", "en", [("volume_up", None)]), ("turn the volume down", "en", [("volume_down", None)]),
    ("mute", "en", [("mute", None)]), ("set volume to 25", "en", [("volume_set", 25)]),
    ("brightness down", "en", [("brightness_down", None)]),
]


@pytest.mark.parametrize("text,lang,expected", CASES)
def test_system_commands_are_recognised(text, lang, expected):
    intent, actions, reply = parse_command(text, lang)
    assert intent == "system" and [(a.control, a.amount) for a in actions] == expected and reply


@pytest.mark.parametrize("text", ["ovozli xabar yubor", "papkani o'chir", "ovoz yozib ol", "Safari ni och",
                                  "Telegramda Aliga ovozli xabar yubor", "ovozni ko'tar va Aliga xabar yubor"])
def test_non_system_commands_are_not_misread(text):
    assert parse_command(text, "uz")[0] != "system"


def test_system_actions_are_low_risk_and_bounded(tmp_path):
    assert safety.classify(Action(type="system", control="volume_up")) == RiskLevel.low
    assert safety.blocked_reason(Action(type="system", control="shutdown"), tmp_path)
    assert safety.blocked_reason(Action(type="system", control="volume_set", amount=500), tmp_path)


def test_voice_command_runs_instantly_without_model_or_confirmation(cfg, storage):
    cfg.fast_path = True
    cfg.confirm_risk = "medium"
    p = ScriptedProvider()
    asked = []
    ad = DryRunAdapter()
    t = Agent(cfg, p, ad, storage, confirm=lambda *a: asked.append(1) or False).run("ovozni ko'tar va yorug'likni oshir")
    assert t.status.value == "success" and t.planner == "rules" and t.llm_calls == 0
    assert [a.control for a in ad.executed] == ["volume_up", "brightness_up"]
    assert p.calls == [] and asked == []


def test_mode_a_runs_all_system_actions(cfg, storage):
    from xadicha.models import Mode

    ad = DryRunAdapter()
    t = Agent(cfg, ScriptedProvider(), ad, storage).run("сделай тише и ярче", "ru", Mode.voice_only)
    assert t.status.value == "success" and [a.control for a in ad.executed] == ["volume_down", "brightness_up"]


# ---------------------------------------------------------------- gapirib bo'linganini sezish

def _feed(ep, seq, dt=0.032):
    t = 0.0
    for level, dur in seq:
        n = int(dur / dt)
        for _ in range(n):
            t += dt
            if ep.feed(level, dt):
                return t
    return None


def test_endpointer_stops_after_speech_then_silence():
    ep = Endpointer()
    stop_at = _feed(ep, [(0.004, 0.3), (0.1, 1.2), (0.004, 3.0)])
    assert ep.reason == "silence" and 2.3 <= stop_at <= 2.6   # 0.3 + 1.2 + ~0.9


def test_endpointer_ignores_short_click():
    ep = Endpointer()
    assert _feed(ep, [(0.004, 0.3), (0.2, 0.1), (0.004, 2.0)]) is None   # 0.1 s — nutq emas


def test_endpointer_gives_up_without_speech():
    ep = Endpointer()
    assert _feed(ep, [(0.004, 7.0)]) is not None and ep.reason == "no_speech"


def test_endpointer_adapts_to_background_noise():
    ep = Endpointer()
    # shovqinli xona: fon 0.03 — u nutq deb hisoblanmaydi; nutq 0.2
    stop_at = _feed(ep, [(0.03, 0.3), (0.03, 1.0), (0.2, 1.0), (0.03, 2.0)])
    assert ep.reason == "silence" and stop_at > 2.0


def test_whisper_hallucinations_are_not_commands():
    assert is_hallucination("Продолжение следует...") and is_hallucination("Thanks for watching!")
    assert not is_hallucination("ovozni ko'tar")


# ---------------------------------------------------------------- avtomatik bajarish (API orqali)

class AutoMic:
    """Soxta mikrofon: endpointer'ga nutq va jimlik beradi (real vaqtdan tezroq)."""
    engine = "fake"

    def __init__(self, text, conf=0.9):
        self.text, self.conf = text, conf

    def warmup(self):
        pass

    def record_until(self, stop, max_seconds=30.0, on_level=None, endpointer=None):
        seq = [(0.004, 0.3), (0.1, 0.6), (0.004, 2.0)]
        for level, dur in seq:
            for _ in range(int(dur / 0.032)):
                if stop.is_set():
                    return np.ones(16000, dtype=np.float32)
                if on_level:
                    on_level(level)
                if endpointer is not None and endpointer.feed(level, 0.032):
                    stop.set()
                time.sleep(0.001)
        stop.wait(2)
        return np.ones(16000, dtype=np.float32)

    def transcribe(self, audio, language=None, prior=None):
        return Transcript(self.text, language or "uz", 0.9, True, asr_confidence=self.conf)


def _svc(cfg, storage, mic):
    cfg.fast_path = True
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc.listener = mic
    events: list[dict] = []
    svc.subscribe(events.append)
    return api_client(svc), svc, events


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_auto_listen_stops_by_itself_and_runs_clear_command(cfg, storage):
    client, svc, events = _svc(cfg, storage, AutoMic("ovozni ko'tar"))
    assert client.post("/api/listen/start?language=uz&auto=true").status_code == 200
    # Foydalanuvchi tugmani qayta bosmaydi — gapirib bo'lganini o'zi sezadi va bajaradi
    assert _wait(lambda: [a.control for a in svc.adapter.executed] == ["volume_up"])
    assert _wait(lambda: not svc.busy)
    assert any(e["type"] == "voice_result" and e["status"] == "started" for e in events)


def test_auto_listen_unclear_command_asks_and_runs_nothing(cfg, storage):
    client, svc, events = _svc(cfg, storage, AutoMic("Staffar in och", 0.42))
    client.post("/api/listen/start?language=uz&auto=true")
    assert _wait(lambda: any(e["type"] == "clarify" for e in events))
    time.sleep(0.2)
    assert svc.adapter.executed == [] and client.get("/api/tasks").json() == []
    c = next(e for e in events if e["type"] == "clarify")
    assert c["text"] == "Staffar in och" and c["analysis"]["suggestion"] == "Safari ni och"


def test_auto_listen_low_asr_confidence_never_runs_even_simple_command(cfg, storage):
    client, svc, events = _svc(cfg, storage, AutoMic("ovozni ko'tar", 0.3))
    client.post("/api/listen/start?language=uz&auto=true")
    assert _wait(lambda: any(e["type"] == "clarify" for e in events))
    assert svc.adapter.executed == []


def test_auto_listen_silence_runs_nothing(cfg, storage):
    client, svc, events = _svc(cfg, storage, AutoMic(""))
    client.post("/api/listen/start?language=uz&auto=true")
    assert _wait(lambda: any(e["type"] == "voice_result" and e["status"] == "empty" for e in events))
    assert svc.adapter.executed == [] and client.get("/api/tasks").json() == []


def test_manual_stop_in_auto_mode_reports_handled(cfg, storage):
    client, svc, _ = _svc(cfg, storage, AutoMic("ovozni pasaytir"))
    client.post("/api/listen/start?language=uz&auto=true")
    time.sleep(0.05)
    r = client.post("/api/listen/stop").json()
    assert r["handled"] is True
    assert _wait(lambda: [a.control for a in svc.adapter.executed] == ["volume_down"])


# ---------------------------------------------------------------- macOS adapter (osascript soxta)

def test_macos_volume_uses_numbers_only_and_verifies(monkeypatch):
    state = {"vol": 30, "muted": "false"}
    scripts = []

    def fake(script, timeout=10):
        scripts.append(script)
        if script.startswith("output volume"):
            return str(state["vol"])
        if script.startswith("set volume output volume"):
            state["vol"] = int(script.split()[4])
            return ""
        if script.startswith("set volume output muted"):
            state["muted"] = script.split()[-1]
            return ""
        if script.startswith("output muted"):
            return state["muted"]
        return ""

    monkeypatch.setattr(mac, "osascript", fake)
    ad = mac.MacOSAdapter()
    r = ad._do_system(Action(type="system", control="volume_up", amount=20))
    assert r.ok and r.verified and state["vol"] == 50
    r = ad._do_system(Action(type="system", control="volume_set", amount=150))   # chegaradan tashqari — 100 ga
    assert state["vol"] == 100
    r = ad._do_system(Action(type="system", control="mute"))
    assert r.verified and state["muted"] == "true"
    r = ad._do_system(Action(type="system", control="brightness_up"))
    assert r.ok and r.verified is None and "key code 144" in scripts[-1]
