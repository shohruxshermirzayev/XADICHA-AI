"""Buyruqni tushunish, aniqlashtirish va ASR ishonchi (qoida asosidagi tahlil; aniqlik o'lchanmagan)."""

from __future__ import annotations

import time

import numpy as np
import pytest
from conftest import ScriptedProvider, api_client

from xadicha.adapters.base import DryRunAdapter
from xadicha.service import XadichaService
from xadicha.speech.stt import Transcript, asr_confidence
from xadicha.understand import ASR_LOW, match_app, normalize, understand


def test_misheard_command_is_not_silently_replaced():
    # Haqiqiy holat: Whisper "Safari ni och" ni "Staffar in och" deb yozgan
    a = understand("Staffar in och", "uz", asr_confidence=0.8)
    assert a.original == "Staffar in och"          # asl matn saqlanadi
    assert a.needs_clarification and a.reason == "unknown_app"
    assert a.suggestion == "Safari ni och"         # faqat taklif
    assert "Safari" in a.candidates


@pytest.mark.parametrize("text,lang,app", [
    ("Safari ni och", "uz", "Safari"), ("Safari'ni och", "uz", "Safari"), ("Telegramni och", "uz", "Telegram"),
    ("Telegram och", "uz", "Telegram"), ("Notes ochib ber", "uz", "Notes"), ("Kalkulyatorni och", "uz", "Calculator"),
    ("Сафари ни оч", "uz", "Safari"), ("Хромни оч", "uz", "Google Chrome"), ("Открой Notes", "ru", "Notes"),
    ("Запусти Telegram", "ru", "Telegram"), ("Open Calculator", "en", "Calculator"), ("open Telegram ni", "uz", "Telegram"),
])
def test_clear_open_app_commands_need_no_clarification(text, lang, app):
    a = understand(text, lang, asr_confidence=0.9)
    assert a.intent == "open_app" and a.app == app and not a.needs_clarification, a


def test_code_switching_russian_verb_uzbek_object():
    a = understand("открой Telegramni", "ru")
    assert a.app == "Telegram"


def test_low_asr_confidence_always_asks_even_if_intent_is_clear():
    a = understand("Safari ni och", "uz", asr_confidence=ASR_LOW - 0.1)
    assert a.needs_clarification and a.reason == "low_asr_confidence" and a.intent_confidence >= 0.9


def test_asr_and_intent_confidence_are_separate():
    a = understand("open sufari", "en", asr_confidence=0.95)
    assert a.needs_clarification and a.intent_confidence < 0.9   # ASR yuqori, niyat esa aniq emas


def test_particle_fix_is_reported_not_hidden():
    norm, notes = normalize("Safari in och")
    assert norm == "Safari ni och" and notes == ["particle_in_to_ni"]
    a = understand("Safari in och", "uz", asr_confidence=0.9)
    assert a.needs_clarification and a.reason == "normalized_particle" and a.original == "Safari in och"


def test_complex_commands_go_to_model_without_clarification():
    for t in ("Ekranda nima bor?", "YouTube'da o'zbek musiqasini qidir va birinchisini qo'y"):
        a = understand(t, "uz", asr_confidence=0.9, llm_available=True)
        assert a.intent == "delegated_to_model" and not a.needs_clarification


def test_rules_only_mode_asks_for_unknown_intent():
    a = understand("Ekranda nima bor", "uz", llm_available=False)
    assert a.needs_clarification and a.reason == "unknown_intent"


def test_unknown_but_plausible_app_is_allowed():
    a = understand("MyLabTool ni och", "uz", asr_confidence=0.9)
    assert a.intent == "open_app" and not a.needs_clarification and a.intent_confidence == 0.5


def test_match_app_aliases_and_fuzzy():
    assert match_app("chrome")[0] == "Google Chrome"
    assert match_app("telegrem")[0] == "Telegram" and match_app("telegrem")[1] < 0.97


def test_asr_confidence_formula():
    assert asr_confidence([]) is None
    hi = asr_confidence([(-0.05, 0.01, 20)])
    lo = asr_confidence([(-1.2, 0.3, 20)])
    assert 0.9 < hi <= 1 and lo < 0.3
    mixed = asr_confidence([(-0.05, 0.0, 90), (-2.0, 0.0, 10)])   # uzun segment ko'proq vazn oladi
    assert mixed > 0.7


class _Listener:
    engine = "fake"

    def __init__(self, text, conf):
        self.text, self.conf = text, conf

    def warmup(self):
        pass

    def record_until(self, stop, max_seconds=30.0, on_level=None):
        stop.wait(1)
        return np.ones(16000, dtype=np.float32)

    def transcribe(self, audio, language=None, prior=None):
        return Transcript(self.text, language or "uz", 0.9, True, asr_confidence=self.conf)


def _client(cfg, storage, text, conf):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc.listener = _Listener(text, conf)
    return api_client(svc), svc


def test_listen_stop_returns_transcript_with_analysis_and_executes_nothing(cfg, storage):
    client, svc = _client(cfg, storage, "Staffar in och", 0.42)
    client.post("/api/listen/start?language=uz")
    time.sleep(0.05)
    r = client.post("/api/listen/stop").json()
    assert r["text"] == "Staffar in och" and r["asr_confidence"] == 0.42
    assert r["analysis"]["needs_clarification"] and r["analysis"]["suggestion"] == "Safari ni och"
    assert svc.adapter.executed == [] and client.get("/api/tasks").json() == []   # hech narsa bajarilmagan


def test_understand_endpoint(cfg, storage):
    client, _ = _client(cfg, storage, "", None)
    r = client.post("/api/understand", json={"text": "Открой Notes", "language": "ru"}).json()
    assert r["intent"] == "open_app" and r["app"] == "Notes" and not r["needs_clarification"]
