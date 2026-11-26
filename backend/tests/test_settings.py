"""Ish vaqtidagi sozlamalar: tekshiruv, darhol qo'llash, saqlash, oflayn rejim (simulyatsiya)."""

from __future__ import annotations

import json
import time

import numpy as np
from conftest import ScriptedProvider, api_client
from test_gemini import FAKE_KEY, Clock, FakeOllama, api_error, gemini
from test_stt_providers import FakeWhisper, recognizer

from xadicha.adapters.base import DryRunAdapter
from xadicha.providers.fallback import FallbackProvider
from xadicha.service import XadichaService


def svc_with(cfg, storage, provider=None):
    return XadichaService(cfg, provider=provider or ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)


def test_put_settings_applies_immediately_and_persists(cfg, storage):
    svc = svc_with(cfg, storage)
    events = []
    svc.subscribe(events.append)
    client = api_client(svc)
    r = client.put("/api/settings", json={"search_mode": "never", "tts_rate": 200, "tts_enabled": False,
                                          "microphone": "MacBook Pro Microphone", "auto_language": False})
    assert r.status_code == 200 and r.json()["values"]["search_mode"] == "never"
    assert cfg.search_mode == "never" and svc.speaker.rate == 200 and svc.speaker.enabled is False
    assert svc.listener.device == "MacBook Pro Microphone" and cfg.auto_language is False
    saved = json.loads((cfg.db_path.parent / "settings.json").read_text())
    assert saved["search_mode"] == "never" and saved["tts_rate"] == 200
    assert any(e["type"] == "settings" for e in events)
    # Qayta ishga tushganda tiklanadi
    cfg2 = type(cfg)(**{**cfg.__dict__, "search_mode": "auto", "tts_rate": 175})
    svc2 = svc_with(cfg2, storage)
    assert svc2.cfg.search_mode == "never" and svc2.speaker.rate == 200


def test_secrets_and_unknown_fields_rejected(cfg, storage):
    client = api_client(svc_with(cfg, storage))
    for body in ({"gemini_api_key": FAKE_KEY}, {"search_mode": "sometimes"}, {"tts_rate": 5000}, {"provider": "claude"}):
        assert client.put("/api/settings", json=body).status_code == 422, body
    assert not (cfg.db_path.parent / "settings.json").exists()
    assert FAKE_KEY not in client.get("/api/settings").text


def test_settings_get_has_readonly_and_no_key(cfg, storage):
    cfg.gemini_api_key = FAKE_KEY
    body = api_client(svc_with(cfg, storage)).get("/api/settings")
    data = body.json()
    assert data["readonly"]["has_gemini_key"] is True and "microphones" in data["options"]
    assert FAKE_KEY not in body.text


def test_vocabulary_and_corrections_reach_recognizer(cfg, storage):
    svc = svc_with(cfg, storage)
    api_client(svc).put("/api/settings", json={"vocabulary": ["Shohrux", "XADICHA AI"], "corrections": {"vs kod": "VS Code"}})
    assert "Shohrux" in svc.stt.vocabulary.terms and "Safari" in svc.stt.vocabulary.terms
    assert svc.stt.vocabulary.correct("vs kod ni och") == "VS Code ni och"


def test_stt_provider_switch_takes_effect(cfg, storage):
    svc = svc_with(cfg, storage)
    api_client(svc).put("/api/settings", json={"stt_provider": "whisper"})
    assert svc.stt.mode == "whisper" and cfg.stt_provider == "whisper"


def test_offline_mode_uses_only_local_providers(cfg, storage):
    g = gemini([])          # chaqirilsa — "kutilmagan so'rov" xatosi
    oll = FakeOllama()
    fp = FallbackProvider(g, oll, clock=Clock())
    cfg.provider, cfg.gemini_api_key = "gemini", FAKE_KEY
    svc = svc_with(cfg, storage, provider=fp)
    svc.stt = recognizer([], whisper=FakeWhisper())
    client = api_client(svc)
    client.put("/api/settings", json={"offline_mode": True})
    assert fp.complete("s", "u", None) and g._client.models.calls == [] and fp.name == "ollama"
    assert not fp.supports_grounding                                  # Google Search ham yo'q
    t = svc.stt.transcribe((0.2 * np.sin(np.linspace(0, 2000, 16000))).astype(np.float32))
    assert t.provider == "whisper:mlx" and svc.stt.gemini._client.interactions.calls == []
    st = client.get("/api/status").json()
    assert st["provider"]["offline"] is True and st["live"]["available"] is False
    assert st["provider"]["primary"]["ok"] is False                   # bulut "ishlayapti" deb ko'rsatilmaydi
    h = client.get("/api/health").json()
    assert h["offline_mode"] is True and h["stt"]["offline"] is True
    client.put("/api/settings", json={"offline_mode": False})
    assert fp.offline is False and svc.stt.offline is False


def test_auto_language_off_forces_selected_language(cfg, storage):
    seen = {}

    class Mic(FakeWhisper):
        def warmup(self):
            pass

        def record_until(self, stop, max_seconds=30.0, on_level=None, endpointer=None):
            stop.wait(0.02)
            return np.ones(16000, dtype=np.float32)

        def transcribe(self, audio, language=None, prior=None):
            seen["language"] = language
            return super().transcribe(audio, language, prior)

    svc = svc_with(cfg, storage)
    svc.listener = Mic()
    svc.stt.whisper = svc.listener
    client = api_client(svc)
    client.put("/api/settings", json={"auto_language": False})
    client.post("/api/listen/start?language=ru")
    client.post("/api/listen/stop")
    assert seen["language"] == "ru"


def test_health_endpoint_is_keyless(cfg, storage):
    cfg.gemini_api_key = FAKE_KEY
    fp = FallbackProvider(gemini([api_error(503, "x", "UNAVAILABLE")], get_error=api_error(503, "x", "UNAVAILABLE")),
                          FakeOllama(), clock=Clock())
    client = api_client(svc_with(cfg, storage, provider=fp))
    r = client.get("/api/health")
    assert r.status_code == 200 and FAKE_KEY not in r.text
    assert set(r.json()) >= {"ok", "provider", "stt", "live", "offline_mode"}
    time.sleep(0)
