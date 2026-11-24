"""Tilni aniqlash mantiqi (Whisper modelisiz)."""

import numpy as np

from xadicha.speech import stt
from xadicha.speech.stt import Listener, pick_language


def test_uzbek_misdetected_as_turkish_is_mapped_to_uz():
    # Whisper o'zbekchani ko'pincha turkcha deb biladi — biz faqat uz/ru/en orasidan tanlaymiz
    probs = [("tr", 0.55), ("uz", 0.20), ("kk", 0.15), ("ru", 0.05), ("en", 0.02)]
    assert pick_language(probs, "tr") == ("uz", 0.20)


def test_russian_kept():
    assert pick_language([("ru", 0.9), ("uk", 0.05)], "ru")[0] == "ru"


def test_no_probs_falls_back():
    assert pick_language(None, "en") == ("en", 0.0)
    assert pick_language(None, "tr") == ("uz", 0.0)


class _Seg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, text, all_probs):
        self.text, self.all_probs, self.calls = text, all_probs, []

    def detect_language(self, audio, vad_filter=False):
        return self.all_probs[0][0], self.all_probs[0][1], self.all_probs

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        return [_Seg(self.text)], None


def _listener(model):
    li = Listener("tiny", engine="faster")
    li._model = model
    return li


def test_transcribe_uses_restricted_language_and_prompt():
    m = _FakeModel("Safari ni och", [("tr", 0.6), ("uz", 0.3)])
    r = _listener(m).transcribe(np.ones(stt.SAMPLE_RATE, dtype=np.float32))
    assert r.language == "uz" and r.detected_raw == "tr" and r.supported
    assert m.calls[0]["language"] == "uz" and "Safari" in m.calls[0]["initial_prompt"]


def test_forced_language_skips_detection():
    m = _FakeModel("Открой Notes", [("en", 0.9)])
    r = _listener(m).transcribe(np.ones(stt.SAMPLE_RATE, dtype=np.float32), language="ru")
    assert r.language == "ru" and m.calls[0]["language"] == "ru"


def test_prompt_echo_on_silence_is_ignored():
    echo = "Safari ni och. Telegram'ni och. Notes ni och. Papka yarat."
    m = _FakeModel(echo, [("uz", 0.9)])
    assert _listener(m).transcribe(np.ones(stt.SAMPLE_RATE, dtype=np.float32)).text == ""


def test_real_short_command_matching_prompt_is_kept():
    m = _FakeModel("Safari ni och", [("uz", 0.9)])
    assert _listener(m).transcribe(np.ones(stt.SAMPLE_RATE, dtype=np.float32)).text == "Safari ni och"


def test_too_short_audio():
    r = _listener(_FakeModel("x", [("uz", 1)])).transcribe(np.zeros(100, dtype=np.float32))
    assert r.text == ""


def test_mlx_repo_names():
    from xadicha.speech.stt import mlx_repo
    assert mlx_repo("large-v3-turbo") == "mlx-community/whisper-large-v3-turbo"
    assert mlx_repo("large-v3") == "mlx-community/whisper-large-v3-mlx"


def test_mlx_unsupported_language_reread_as_uzbek(monkeypatch):
    li = Listener("tiny", engine="faster")
    li.engine = "mlx"
    calls = []

    def fake(audio, language):
        calls.append(language)
        return ("Safari ni och", "uz", 0.8) if language == "uz" else ("Safari notch", "tr", 0.3)

    monkeypatch.setattr(li, "_mlx_full", fake)
    r = li.transcribe(np.ones(stt.SAMPLE_RATE, dtype=np.float32))
    assert r.language == "uz" and r.detected_raw == "tr" and calls == [None, "uz"]
    assert r.asr_confidence == 0.8


def test_mlx_failure_falls_back_to_faster(monkeypatch):
    li = _listener(_FakeModel("Открой Notes", [("ru", 0.9)]))
    li.engine = "mlx"
    monkeypatch.setattr(li, "_mlx_full", lambda a, l: (_ for _ in ()).throw(RuntimeError("no mlx")))
    r = li.transcribe(np.ones(stt.SAMPLE_RATE, dtype=np.float32))
    assert r.text == "Открой Notes" and li.engine == "faster"
