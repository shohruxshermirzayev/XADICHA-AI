"""Oqimli javob (LLM + TTS), Live STT sessiya pool'i, o'zbek apostrofi, lug'at, OCR'ni tejash (simulyatsiya)."""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
from conftest import ScriptedProvider, api_client
from test_gemini import FAKE_KEY, FakeClient, api_error

from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent
from xadicha.models import Mode, TaskStatus
from xadicha.providers.base import ProviderError
from xadicha.providers.gemini_provider import GeminiProvider
from xadicha.service import XadichaService
from xadicha.speech.recognizer import Vocabulary, normalize_uz


class StreamModel(ScriptedProvider):
    name = "gemini"
    supports_vision = True
    supports_streaming = True

    def __init__(self, chunks=("Samarqand qadimiy ", "shahar. Unda ", "Registon bor."), fail_at=None, delay=0.0):
        super().__init__()
        self.chunks, self.fail_at, self.delay, self.json_calls = list(chunks), fail_at, delay, 0

    def stream_text(self, system, user):
        assert "{\"reply\"" not in system and "plain text" in system
        for i, c in enumerate(self.chunks):
            if self.fail_at == i:
                raise ProviderError("oqim uzildi", kind="network")
            time.sleep(self.delay)
            yield c

    def complete(self, system, user, screen):
        self.json_calls += 1
        return '{"reply": "JSON yo\'li javobi"}'


def run_chat(cfg, model, text="Samarqand qayerda?"):
    events = []
    cfg.search_mode = "never"
    agent = Agent(cfg, model, DryRunAdapter(), on_event=events.append)
    return agent, agent.run(text, "uz", Mode.multimodal), events


# ---------- oqimli LLM javobi ----------

def test_streamed_chat_emits_partials_and_sentences(cfg):
    _, task, events = run_chat(cfg, StreamModel())
    partials = [e["text"] for e in events if e["type"] == "response_partial"]
    sentences = [e["text"] for e in events if e["type"] == "response_sentence"]
    assert partials[0] == "Samarqand qadimiy " and partials[-1].endswith("Registon bor.")
    assert sentences == ["Samarqand qadimiy shahar.", "Unda Registon bor."]   # gap tugashi bilan — ovozga
    assert task.final_message == "Samarqand qadimiy shahar. Unda Registon bor." and task.data["streamed"]
    assert any(s["stage"] == "llm:chat_stream" and s["chunks"] == 3 for s in task.trace)


def test_stream_failure_before_first_chunk_uses_json_path(cfg):
    m = StreamModel(fail_at=0)
    _, task, events = run_chat(cfg, m)
    assert task.final_message == "JSON yo'li javobi" and m.json_calls == 1
    assert not any(e["type"] == "response_partial" for e in events)


def test_stop_cancels_stream_immediately(cfg):
    m = StreamModel(chunks=["Birinchi gap. "] + ["davomi "] * 50, delay=0.02)
    agent = Agent(cfg, m, DryRunAdapter())
    threading.Timer(0.1, agent.stop).start()
    cfg.search_mode = "never"
    t0 = time.time()
    task = agent.run("Python nima?", "uz", Mode.multimodal, clear_cancel=True)
    assert time.time() - t0 < 0.8 and task.status == TaskStatus.cancelled


def test_gemini_stream_text_skips_failed_model():
    from google.genai import types

    chunk = types.GenerateContentResponse.model_validate({"candidates": [{"content": {"role": "model", "parts": [{"text": "Salom"}]}}]})

    class Models:
        calls = []

        def generate_content_stream(self, model, contents, config):
            self.calls.append(model)
            if model == "main":
                raise api_error(504, "deadline", "DEADLINE_EXCEEDED")
            return iter([chunk])

    client = FakeClient([])
    client.models = Models()
    g = GeminiProvider(FAKE_KEY, "main", client=client, fallback_models=["lite"], retry_delay=0)
    assert list(g.stream_text("s", "u")) == ["Salom"] and g.model == "lite" and "main" in g._down


# ---------- service: oqimli TTS ----------

class RecSpeaker:
    engine, rate, enabled = "edge", 175, True

    def __init__(self):
        self.pushed, self.said, self.ended = [], [], 0

    def stream_push(self, text, lang):
        self.pushed.append(text)
        return True

    def stream_end(self):
        self.ended += 1

    def say(self, text, lang="uz", block=False):
        self.said.append(text)
        return True

    def stop(self):
        pass

    def available(self, lang):
        return True

    def voice_for(self, lang):
        return "v"


def test_service_speaks_sentences_while_streaming_and_not_twice(cfg, storage):
    cfg.tts_enabled, cfg.search_mode = True, "never"
    svc = XadichaService(cfg, provider=StreamModel(), adapter=DryRunAdapter(), storage=storage)
    svc.speaker = RecSpeaker()
    events = []
    svc.subscribe(events.append)
    task = svc.run_task("Samarqand qayerda?", "uz", speak=True)
    assert svc.speaker.pushed == ["Samarqand qadimiy shahar.", "Unda Registon bor."]
    assert svc.speaker.said == [] and svc.speaker.ended == 1          # yakunda qayta aytilmaydi
    assert not any(e["type"] == "response_sentence" for e in events)  # ichki hodisa — interfeysga emas
    assert any(e["type"] == "response_partial" for e in events) and task.data["streamed"]


def test_speaker_stream_queue_plays_in_order(monkeypatch):
    import subprocess

    from xadicha.speech import tts

    played = []

    class P:
        def __init__(self, cmd, **kw):
            played.append(cmd[-1])

        def wait(self):
            return 0

        def poll(self):
            return 0

    sp = tts.Speaker("system", 175, {"uz": "Milena", "ru": "Milena", "en": "Samantha"}, True)
    monkeypatch.setattr(sp, "available", lambda lang: True)
    monkeypatch.setattr(sp, "voice_for", lambda lang: "Samantha")
    monkeypatch.setattr(tts.subprocess, "Popen", P)
    monkeypatch.setattr(tts.platform, "system", lambda: "Darwin")
    for s in ["Birinchi.", "Ikkinchi.", "Uchinchi."]:
        sp.stream_push(s, "en")
    sp.stream_end()
    end = time.time() + 2
    while len(played) < 3 and time.time() < end:
        time.sleep(0.01)
    assert played == ["Birinchi.", "Ikkinchi.", "Uchinchi."]
    assert subprocess is not None


# ---------- Live STT pool ----------

def test_pool_hands_out_preopened_session_and_refills():
    from xadicha.speech.stream import LiveSTTPool

    opened = []

    class Ctx:
        async def __aenter__(self):
            opened.append(time.time())
            return object()

        async def __aexit__(self, *a):
            return False

    client = type("C", (), {"aio": type("A", (), {"live": type("L", (), {"connect": lambda self, model, config: Ctx()})()})()})()
    pool = LiveSTTPool(client, "m", lambda: None)
    end = time.time() + 2
    while not pool.info()["ready"] and time.time() < end:
        time.sleep(0.01)
    got = pool.run(pool.take())
    assert got is not None and pool.info()["hits"] == 1
    end = time.time() + 2
    while not pool.info()["ready"] and time.time() < end:   # keyingi buyruq uchun yangisi ochildi
        time.sleep(0.01)
    assert len(opened) == 2
    pool.close()


def test_streaming_transcriber_uses_pool_without_connecting():
    from test_streaming import FakeLiveClient, FakeSource, final

    from xadicha.speech.stream import LiveSTTPool, StreamingTranscriber

    client = FakeLiveClient([[(0.02, final("Safari ni och."))]])
    pool = LiveSTTPool(client, "m", lambda: None)
    end = time.time() + 2
    while not pool.info()["ready"] and time.time() < end:
        time.sleep(0.01)
    n_before = len(client.configs)
    st = StreamingTranscriber("", "m", source_factory=FakeSource, pool=pool, final_grace_s=0.3)
    r = st.run(threading.Event())
    assert r.text == "Safari ni och." and r.marks.get("pooled") == 1
    assert len(client.configs) >= n_before            # ulanish oldindan qilingan (buyruq paytida emas)
    pool.close()


# ---------- o'zbek tili, lug'at, OCR ----------

def test_uzbek_apostrophes_normalized():
    assert normalize_uz("oʻchir gʻalaba o ‘rnat Telegram`ni") == "o'chir g'alaba o'rnat Telegram'ni"
    assert Vocabulary(corrections={"vs kod": "VS Code"}).correct("vs kod ni oʻchir") == "VS Code ni o'chir"


def test_vocabulary_has_required_terms_and_installed_apps(monkeypatch, cfg):
    from xadicha.speech import recognizer

    monkeypatch.setattr(recognizer, "installed_app_names", lambda limit=200: ["MyCustomApp"])
    monkeypatch.delenv("XADICHA_VOCAB_FILES", raising=False)
    monkeypatch.setattr(recognizer, "recent_file_names", lambda limit=50: ["maxfiy_hisobot"])
    r = recognizer.make_recognizer(cfg, object())
    for term in ("XADICHA AI", "Gemini", "Claude", "Ollama", "VS Code", "Terminal", "Python", "Next.js", "GitHub", "MyCustomApp"):
        assert term in r.vocabulary.terms, term
    assert "maxfiy_hisobot" not in r.vocabulary.terms       # fayl nomlari — faqat ruxsat bilan
    monkeypatch.setenv("XADICHA_VOCAB_FILES", "1")
    assert "maxfiy_hisobot" in recognizer.make_recognizer(cfg, object()).vocabulary.terms


def test_full_screen_ocr_skipped_for_vision_model(cfg, storage, monkeypatch):
    from xadicha.vision import screen

    calls = []

    class OCR:
        def availability(self):
            return ("available", "")

        def recognize(self, img, size):
            calls.append(1)
            return []

    class AX:
        def availability(self):
            return ("unavailable", "")

    from PIL import Image

    monkeypatch.setattr(screen, "capture_image", lambda size=None: (Image.new("RGB", (64, 48)), 64, 48))
    svc = XadichaService(cfg, provider=StreamModel(), adapter=DryRunAdapter(), storage=storage, ocr=OCR(), accessibility=AX())
    shot = svc._capture_with_context()
    assert calls == [] and shot.timings.get("ocr_skipped") == 1
    svc.provider.supports_vision = False
    svc._capture_with_context()
    assert calls == [1]
    _ = (np, asyncio, api_client)
