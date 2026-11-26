"""Stage 1: o'zbek yozuvi afzalligi, sozlamalar, baholash to'plamlari (simulyatsiya)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from conftest import ScriptedProvider, api_client

from xadicha.adapters.base import DryRunAdapter
from xadicha.lang import latin_to_cyrillic_uz
from xadicha.router import route
from xadicha.service import XadichaService

VAL = Path(__file__).resolve().parent.parent / "validation"


@pytest.mark.parametrize("latin,cyr", [
    ("ovozni 30 gacha pasaytir", "овозни 30 гача пасайтир"),
    ("o‘zbekiston tarixi haqida qidir", "ўзбекистон тарихи ҳақида қидир"),
    ("eng yaxshi choyxona", "энг яхши чойхона"),
    ("shahar yangiliklari", "шаҳар янгиликлари"),
])
def test_latin_to_cyrillic(latin, cyr):
    assert latin_to_cyrillic_uz(latin) == cyr


def test_brand_names_stay_latin():
    out = latin_to_cyrillic_uz("VS Code ni och va Safari'ni yop", keep=["VS Code", "Safari"])
    assert out.startswith("VS Code ни оч") and "Safari'ni" in out


@pytest.mark.parametrize("latin", ["ovozni ko'tar", "yorug'likni oshir", "zaryad qancha"])
def test_cyrillic_transcripts_still_route_the_same(latin):
    a, b = route(latin, "uz"), route(latin_to_cyrillic_uz(latin), "uz")
    assert (a.path, [x.control for x in a.actions]) == (b.path, [x.control for x in b.actions])


def test_settings_accept_barge_in_and_uz_script(cfg, storage):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    client = api_client(svc)
    r = client.put("/api/settings", json={"live_barge_in": True, "uz_script": "cyrillic"}).json()["values"]
    assert r["live_barge_in"] is True and r["uz_script"] == "cyrillic" and cfg.uz_script == "cyrillic"
    assert svc._apply_uz_script("ovozni ko'tar", "uz") == "овозни кўтар"
    assert svc._apply_uz_script("open Safari", "en") == "open Safari"        # faqat o'zbekcha
    assert client.put("/api/settings", json={"uz_script": "arabic"}).status_code == 422


def _rows(name):
    return list(csv.DictReader((VAL / name).open(encoding="utf-8")))


def test_evaluation_sets_are_disjoint_and_well_formed():
    dev, held, reg = _rows("human_dev.csv"), _rows("human_heldout_v2.csv"), _rows("speech_validation_set.csv")
    texts = lambda rows: {r["text"].lower() for r in rows if r["text"]}  # noqa: E731
    assert not texts(held) & texts(dev) and not texts(held) & texts(reg)   # ko'rilmagan to'plam alohida
    groups = {(r["lang"], r["script"], r["kind"]) for r in held}
    for g in [("uz", "latn", "command"), ("uz", "cyrl", "command"), ("ru", "cyrl", "command"), ("en", "latn", "command"),
              ("", "", "silence")]:
        assert g in groups, g
    assert any(r["kind"] == "mixed" for r in held)


# ---------- inson nutqi baholash vositasi ----------

def test_consent_is_required_for_recording():
    from xadicha.validation.speech import ask_consent

    assert ask_consent("ha") and ask_consent("да") and ask_consent("yes")
    assert not ask_consent("yo'q") and not ask_consent("") and not ask_consent("keyin")


def test_record_session_refuses_without_consent(cfg, tmp_path, monkeypatch):
    import types

    from xadicha.validation import speech

    args = types.SimpleNamespace(set="heldout", only="", limit=1, selected="uz", consent="yo'q")
    monkeypatch.setattr(speech, "RESULTS_DIR", tmp_path)
    assert speech.record_session(args, cfg) == 3 and not any(tmp_path.iterdir())   # hech narsa yozilmadi


def test_array_source_streams_audio_then_silence():
    import threading
    import time

    import numpy as np

    from xadicha.validation.speech import ArraySource

    got = []
    src = ArraySource(np.full(16000, 0.1, dtype=np.float32), realtime=False, lead_s=0.0)
    src.start(got.append)
    time.sleep(0.2)
    src.stop()
    loud = sum(1 for b in got if any(b))
    assert loud == -(-16000 // 1024) and len(got) > loud           # nutq bo'laklari, keyin jimlik
    _ = threading


def test_rescore_compares_providers_on_same_audio(cfg, tmp_path, monkeypatch):
    import types

    import numpy as np

    from xadicha.speech.stt import Transcript
    from xadicha.validation import speech

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    speech.write_wav(audio_dir / "hh_uzl_08.wav", np.zeros(8000, dtype=np.float32))

    class Fake:
        def __init__(self, text, engine):
            self.text, self.engine, self.model_name = text, engine, "m"

        def warmup(self):
            pass

        def transcribe(self, audio, language=None, prior=None):
            return Transcript(self.text, "uz", 0.9, True)

    monkeypatch.setattr(speech, "make_provider", lambda name, cfg, **k: Fake(
        "batareya necha foiz bo'ldi" if name == "gemini" else "batareya nechchi", name))
    saved = {}
    monkeypatch.setattr(speech, "save_result", lambda kind, data, *a: saved.update(data) or tmp_path / "r.json")
    args = types.SimpleNamespace(rescore=str(tmp_path), providers="gemini,gemini-live", selected="uz", engines="", models="")
    assert speech.rescore(args, cfg) == 0
    comp = saved["comparisons"]
    assert comp["gemini"]["items"][0]["wer"] == 0.0 and comp["gemini"]["items"][0]["intent_ok"]
    assert (tmp_path / "r.csv").exists() and "provider" in (tmp_path / "r.csv").read_text().splitlines()[0]


def test_array_source_starts_with_lead_silence_for_vad_calibration():
    import time

    import numpy as np

    from xadicha.validation.speech import ArraySource

    got = []
    src = ArraySource(np.full(4096, 0.1, dtype=np.float32), realtime=False, lead_s=0.5)
    src.start(got.append)
    time.sleep(0.2)
    src.stop()
    assert not any(got[0]) and not any(got[6]) and any(got[7])     # 7 × 64 ms jimlik, keyin nutq
