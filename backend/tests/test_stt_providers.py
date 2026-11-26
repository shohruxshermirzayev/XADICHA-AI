"""STT qatlami: Gemini Transcribe + Whisper, rejimlar, zaxira, lug'at, til aniqlash.

SIMULYATSIYA: Gemini mijozi va Whisper soxta (tarmoq va mikrofon yo'q). Haqiqiy sinov:
`python -m xadicha.validation.stt_compare` (kalit va internet kerak; audio — sintetik TTS).
"""

from __future__ import annotations

import base64
import io
import json
import time
import wave

import numpy as np
import pytest
from conftest import ScriptedProvider, api_client

from xadicha.adapters.base import DryRunAdapter
from xadicha.config import load_config
from xadicha.providers.base import ProviderError
from xadicha.service import XadichaService
from xadicha.speech.recognizer import (
    GeminiTranscriber, SpeechRecognizer, Vocabulary, is_silence, make_recognizer, wav_bytes,
)
from xadicha.speech.stt import Transcript

SPEECH = (0.2 * np.sin(np.linspace(0, 2000, 16000))).astype(np.float32)   # 1 s "nutq"
SILENCE = np.zeros(16000, dtype=np.float32)


class FakeInteractions:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def create(self, **body):
        self.calls.append(body)
        item = self.outputs.pop(0)
        if isinstance(item, BaseException):
            raise item
        return type("Interaction", (), {"status": "completed", "output_text": item})()


class FakeGenaiClient:
    def __init__(self, outputs):
        self.interactions = FakeInteractions(outputs)


class StatusError(Exception):
    """Interactions API xatosiga o'xshash (APIStatusError: .status_code)."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.status_code = code


class FakeWhisper:
    engine = "mlx"
    model_name = "large-v3-turbo"

    def __init__(self, text="whisper matni", lang="uz"):
        self.text, self.lang, self.calls = text, lang, 0

    def transcribe(self, audio, language=None, prior=None):
        self.calls += 1
        return Transcript(self.text, language or self.lang, 0.8, True, asr_confidence=0.7)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def recognizer(outputs, mode="auto", vocab=None, clock=None, whisper=None):
    g = GeminiTranscriber("k" * 20, "gemini-3.5-transcribe", client=FakeGenaiClient(outputs))
    return SpeechRecognizer(whisper or FakeWhisper(), g, mode, vocab or Vocabulary(), clock=clock or Clock())


# ---------- yordamchilar ----------

def test_wav_bytes_is_16k_mono_pcm():
    with wave.open(io.BytesIO(wav_bytes(SPEECH))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 16000)


def test_silence_detection():
    assert is_silence(SILENCE) and is_silence(SPEECH[:1000]) and not is_silence(SPEECH)


def test_vocabulary_file_merges_terms_and_applies_corrections(tmp_path):
    f = tmp_path / "vocabulary.json"
    f.write_text(json.dumps({"terms": ["Shohrux", "XADICHA AI"], "corrections": {"telegram ni": "Telegram'ni",
                                                                              "vs kod": "VS Code"}}), encoding="utf-8")
    v = Vocabulary.load(f)
    assert "Shohrux" in v.terms and "Safari" in v.terms and len(v.terms) <= 1000
    assert v.correct("Telegram ni och va vs kod ni yop") == "Telegram'ni och va VS Code ni yop"
    assert v.correct("vs kodlash") == "vs kodlash"        # so'z ichida almashtirilmaydi


def test_broken_vocabulary_file_does_not_crash(tmp_path):
    f = tmp_path / "v.json"
    f.write_text("{buzuq", encoding="utf-8")
    assert Vocabulary.load(f).terms                      # standart lug'at bilan davom etadi


# ---------- Gemini Transcribe ----------

def test_gemini_request_has_audio_vocabulary_and_auto_language():
    r = recognizer(["Xadicha, Telegram'ni och."])
    t = r.transcribe(SPEECH, None, prior="uz")
    body = r.gemini._client.interactions.calls[0]
    assert body["model"] == "gemini-3.5-transcribe"
    part = body["input"][0]
    assert part["type"] == "audio" and part["mime_type"] == "audio/wav"
    assert base64.b64decode(part["data"])[:4] == b"RIFF"
    tc = body["generation_config"]["transcription_config"]
    assert "Telegram" in tc["custom_vocabulary"] and "language_codes" not in tc   # avtomatik til, code-switching
    assert (t.text, t.provider, t.model, t.language) == ("Xadicha, Telegram'ni och.", "gemini", "gemini-3.5-transcribe", "uz")
    assert t.asr_confidence is None                       # Gemini ishonch bermaydi — to'qilmaydi


def test_forced_language_is_sent_as_bcp47():
    r = recognizer(["Открой Notes"])
    t = r.transcribe(SPEECH, "ru")
    assert r.gemini._client.interactions.calls[0]["generation_config"]["transcription_config"]["language_codes"] == ["ru-RU"]
    assert t.language == "ru"


@pytest.mark.parametrize("text,lang", [
    ("Safari ni och va papka yarat", "uz"),
    ("Сафари ни оч ва папка ярат", "uz"),                # o'zbek kirill — rus deb olinmaydi
    ("Открой Safari и создай папку", "ru"),
    ("Open Safari and create a folder", "en"),
    ("Рабочий столдаги Excel файлни оч", "uz"),           # aralash (ru+uz)
])
def test_language_detected_from_gemini_text(text, lang):
    assert recognizer([text]).transcribe(SPEECH, None, prior="uz").language == lang


def test_corrections_applied_to_gemini_output():
    r = recognizer(["vs kod ni och"], vocab=Vocabulary(corrections={"vs kod": "VS Code"}))
    assert r.transcribe(SPEECH).text == "VS Code ni och"


def test_silence_is_not_sent_to_gemini():
    r = recognizer([])
    t = r.transcribe(SILENCE)
    assert t.text == "" and r.gemini._client.interactions.calls == [] and r.whisper.calls == 0


# ---------- zaxira va rejimlar ----------

@pytest.mark.parametrize("exc,kind", [
    (StatusError(400, "API key not valid. Please pass a valid API key."), "auth"),
    (StatusError(429, "Resource exhausted"), "quota"),
    (StatusError(503, "Unavailable"), "server"),
    (ConnectionError("offline"), "network"),
])
def test_gemini_failure_falls_back_to_whisper_with_metadata(exc, kind):
    clock = Clock()
    r = recognizer([exc], clock=clock)
    t = r.transcribe(SPEECH, None, prior="uz")
    assert t.text == "whisper matni" and t.provider == "whisper:mlx" and t.fallback_from == "gemini"
    assert t.fallback_reason and "k" * 20 not in t.fallback_reason
    # Keyingi so'rov cooldown davomida Gemini'ga yuborilmaydi (takroriy keraksiz so'rov yo'q)
    r.transcribe(SPEECH)
    assert len(r.gemini._client.interactions.calls) == 1 and r.whisper.calls == 2
    assert r.info()["active"] == "whisper" and r.info()["gemini"]["error"]


def test_gemini_retried_after_cooldown():
    clock = Clock()
    r = recognizer([StatusError(503, "x"), "qayta ishladi"], clock=clock)
    r.transcribe(SPEECH)
    clock.t += 61
    t = r.transcribe(SPEECH)
    assert t.provider == "gemini" and t.text == "qayta ishladi" and r.info()["gemini"]["error"] == ""


def test_whisper_mode_never_calls_gemini():
    r = recognizer(["ishlatilmaydi"], mode="whisper")
    t = r.transcribe(SPEECH)
    assert t.provider == "whisper:mlx" and not t.fallback_from and r.gemini._client.interactions.calls == []


def test_gemini_mode_without_key_reports_reason(monkeypatch):
    rec = SpeechRecognizer(FakeWhisper(), None, "gemini", gemini_error="GEMINI_API_KEY o'rnatilmagan")
    t = rec.transcribe(SPEECH)
    assert t.provider == "whisper:mlx" and t.fallback_from == "gemini" and "GEMINI_API_KEY" in t.fallback_reason


def test_auto_mode_without_key_is_plain_whisper_not_fallback():
    t = SpeechRecognizer(FakeWhisper(), None, "auto").transcribe(SPEECH)
    assert t.provider == "whisper:mlx" and t.fallback_from == ""


def test_make_recognizer_from_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XADICHA_STT", "whisper")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyFAKE-test-key-0123456789abcdefghijk")
    cfg = load_config()
    r = make_recognizer(cfg, FakeWhisper())
    assert r.mode == "whisper" and r.gemini is None
    cfg.stt_provider = "auto"
    r2 = make_recognizer(cfg, FakeWhisper())
    assert r2.gemini is not None and r2.gemini.model == cfg.gemini_stt_model


def test_invalid_stt_mode_warns(monkeypatch):
    monkeypatch.setenv("XADICHA_STT", "google")
    cfg = load_config()
    assert cfg.stt_provider == "auto" and any("XADICHA_STT" in w for w in cfg.warnings)


# ---------- service integratsiyasi ----------

class Mic(FakeWhisper):
    """Soxta mikrofon + Whisper (service listener o'rnida)."""

    def warmup(self):
        pass

    def record_until(self, stop, max_seconds=30.0, on_level=None, endpointer=None):
        stop.wait(0.05)
        return SPEECH


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_service_uses_gemini_and_reports_provider_in_events_and_trace(cfg, storage):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc.listener = Mic()
    svc.stt = recognizer(["Notes ni och"], whisper=svc.listener)
    events: list[dict] = []
    svc.subscribe(events.append)
    client = api_client(svc)
    assert client.post("/api/listen/start?language=uz").status_code == 200
    r = client.post("/api/listen/stop").json()
    assert r["text"] == "Notes ni och"
    tr = next(e for e in events if e["type"] == "transcript")
    assert tr["stt_provider"] == "gemini" and tr["stt_model"] == "gemini-3.5-transcribe" and tr["language"] == "uz"
    asr = next(s for s in svc._voice_trace if s["stage"] == "asr")
    assert asr["provider"] == "gemini"
    st = client.get("/api/status").json()["stt"]
    assert st["mode"] == "auto" and st["last"]["provider"] == "gemini"


def test_service_fallback_to_whisper_is_visible(cfg, storage):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc.listener = Mic(text="Safari ni och")
    svc.stt = recognizer([ConnectionError("internet yo'q")], whisper=svc.listener)
    events: list[dict] = []
    svc.subscribe(events.append)
    client = api_client(svc)
    client.post("/api/listen/start?language=uz")
    client.post("/api/listen/stop")
    tr = next(e for e in events if e["type"] == "transcript")
    assert tr["stt_provider"] == "whisper:mlx" and tr["fallback_from"] == "gemini" and tr["fallback_reason"]
    asr = next(s for s in svc._voice_trace if s["stage"] == "asr")
    assert "gemini → whisper" in asr["reason"]
