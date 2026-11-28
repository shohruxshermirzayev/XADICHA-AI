"""VAD tuzatishi va inson nutqi bilan baholash vositalari (2026-11-27).

SIMULYATSIYA: signal darajalari — sintetik ketma-ketlik, mikrofon va API yo'q. Haqiqiy o'lchov:
`python -m xadicha.validate fleurs --vad|--stt` (Google FLEURS, haqiqiy inson nutqi) — docs/HUMAN_SPEECH_EVAL.md.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from xadicha.providers.base import ProviderError
from xadicha.speech.stt import Endpointer, Transcript, is_prompt_echo, is_repetition
from xadicha.validation import fleurs, speech


def feed(ep, seq, dt):
    t = 0.0
    for level, dur in seq:
        for _ in range(round(dur / dt)):
            t += dt
            if ep.feed(level, dt):
                return t
    return None


def syllables(level, dur, gap_level, syl=0.24, gap=0.07):
    """Nutq: bo'g'inlar orasida qisqa pasayish (haqiqiy nutqdagi kabi)."""
    out, t = [], 0.0
    while t < dur:
        out += [(level, syl), (gap_level, gap)]
        t += syl + gap
    return out


# ---------- VAD (Endpointer) ----------

@pytest.mark.parametrize("dt", [0.032, 0.064])   # ilovadagi bo'laklar: Listener 32 ms (BLOCK), oqimli STT 64 ms
def test_speech_detected_when_user_speaks_right_after_enter(dt):
    # Kalibrlash nutqqa to'g'ri keladi. Eski VAD: fon nutq darajasida qolib, nutq umuman sezilmasdi (no_speech).
    # So'zlar orasidagi qisqa pauzalar (0.12 s) haqiqiy fonni ko'rsatadi — chegara bir necha so'zda tiklanadi
    ep = Endpointer()
    stop = feed(ep, syllables(0.08, 2.5, 0.004, syl=0.3, gap=0.12) + [(0.004, 4.0)], dt)
    assert ep.heard and ep.reason == "silence" and stop is not None


def test_decision_does_not_depend_on_chunk_size():
    # Eski EMA har bo'lakda 0.05 edi — 10 ms bo'laklarda fon nutq darajasiga 6 barobar tez ko'tarilardi
    stops = {}
    for dt in (0.01, 0.032, 0.064):
        ep = Endpointer()
        stops[dt] = feed(ep, [(0.004, 0.6)] + syllables(0.03, 2.0, 0.009) + [(0.004, 3.0)], dt)
        assert ep.reason == "silence", dt
    assert max(stops.values()) - min(stops.values()) < 0.3


def test_quiet_speech_parts_do_not_raise_noise_floor():
    ep = Endpointer()
    feed(ep, [(0.004, 0.5)] + syllables(0.03, 1.0, 0.011), 0.01)   # sokin nutq, pasayishlari fondan 3 barobar
    assert ep.floor < 0.006 and ep.heard


def test_short_sound_before_speech_does_not_end_recording():
    # nafas/stul g'ijirlashi (0.25 s), 1.3 s pauza, keyin gap — qisqa tovushdan keyin kutish uzunroq
    ep = Endpointer()
    stop = feed(ep, [(0.004, 0.5), (0.1, 0.25), (0.004, 1.3), (0.1, 1.2), (0.004, 3.0)], 0.032)
    assert stop is not None and stop > 0.5 + 0.25 + 1.3 + 1.2


def test_slowly_rising_noise_is_not_speech():
    ep = Endpointer()
    ramp = [(0.004 * (1 + 3 * i / 20), 0.1) for i in range(20)]   # 2 s davomida fon 4 barobar ortadi
    feed(ep, [(0.004, 0.5)] + ramp + [(0.016, 5.0)], 0.032)
    assert ep.reason == "no_speech" and not ep.heard


# ---------- Whisper xayolotlari ----------

def test_repetition_is_dropped_only_with_low_confidence():
    assert is_repetition("Pobre. Pobre. Pobre.", 0.29)
    assert not is_repetition("Pobre. Pobre. Pobre.", 0.9)
    assert not is_repetition("Pobre. Pobre. Pobre.", None)     # ishonch noma'lum — tashlamaymiz
    assert not is_repetition("ovozni ko'tar", 0.2)


def test_prompt_echo_rules():
    assert is_prompt_echo("Play a song on YouTube.", 0.368)    # real yozuvdagi xayolot (2026-11-26)
    assert is_prompt_echo("Telegramni och", 0.3)               # apostrofsiz ham — so'rov gapi
    assert not is_prompt_echo("Open Safari.", 0.8)             # aniq eshitilgan — hech qachon tashlanmaydi
    assert not is_prompt_echo("See you next time.", 0.3)       # so'rovda yo'q
    assert not is_prompt_echo("ovozni 60 gacha ko'tar", 0.3)


# ---------- baholash vositasi ----------

class FakeLi:
    engine, model_name = "fake", "fake-1"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def transcribe(self, audio, language=None, prior=None):
        o = self.outcomes.pop(0)
        if isinstance(o, BaseException):
            raise o
        return o


ROW = {"id": "x1", "kind": "command", "lang": "uz", "script": "latn", "text": "Safari ni och", "intent": "open_app",
       "entity": "Safari"}


def test_rescore_waits_on_quota_and_retries():
    waits = []
    li = FakeLi([ProviderError("Gemini Transcribe: kvota (429)", "quota"), Transcript("Safari ni och", "uz", 0.9, True)])
    rec = speech.score_safely(li, ROW, np.zeros(16000, np.float32), "uz", sleep=waits.append, wait_s=3.0)
    assert waits == [3.0] and rec["hypothesis"] == "Safari ni och" and rec["wer"] == 0.0


def test_provider_error_is_recorded_and_excluded_from_wer():
    li = FakeLi([ProviderError("tarmoq yo'q", "network")])
    rec = speech.score_safely(li, ROW, np.zeros(16000, np.float32), "uz", sleep=lambda s: None)
    assert rec["provider_error"] and "wer" not in rec
    ok = speech.score_safely(FakeLi([Transcript("Safari ni och", "uz", 0.9, True)]), ROW, np.zeros(16000, np.float32), "uz")
    s = speech.summarize([rec, ok])["overall"]
    assert s["provider_errors"] == 1 and s["n_commands"] == 1 and s["wer_mean"] == 0.0


def test_prompt_echo_without_speech_is_not_scored_as_transcript():
    li = FakeLi([Transcript("Play a song on YouTube.", "en", 0.9, True, asr_confidence=0.37)])
    rec = speech._transcribe_and_score(li, ROW, np.zeros(16000, np.float32), "uz", no_speech=True)
    assert rec["hypothesis"] == "" and rec["asr_filter"] == "prompt_echo_without_speech"


def test_retry_after_is_read_from_error_message():
    e = ProviderError("kvota", "quota")
    e.__cause__ = RuntimeError("Please retry in 41s or upgrade")
    assert speech._retry_after(e, 25.0) == 42.0
    assert speech._retry_after(ProviderError("x", "quota"), 25.0) == 25.0


def test_vad_replay_labels_saved_recordings():
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(16000 * 7) * 0.003).astype(np.float32)
    assert speech.vad_replay(noise) == "no_speech"
    t = np.arange(16000) / 16000
    talk = np.concatenate([noise[:8000], (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), noise[:32000]])
    assert speech.vad_replay(talk) == "silence"


def test_mic_check_reports_and_lets_user_quit():
    class Mic:
        engine, model_name = "fake", "fake"

        def record_until(self, stop, max_seconds=8, endpointer=None):
            audio = np.full(16000 * 2, 0.001, np.float32)
            for i in range(0, len(audio), 512):
                endpointer.feed(0.001, 512 / 16000)
            return audio

    answers = iter(["", "q"])
    assert speech.mic_check(Mic(), ask=lambda _p: next(answers)) is None   # nutq yo'q → foydalanuvchi chiqdi


# ---------- FLEURS ----------

def test_parse_tsv_keeps_only_numeric_wav_names():
    tsv = ("1591\t4967621184651376579.wav\tRaw text.\traw text\tr a w |\t279360\tFEMALE\n"
           "1\t../../etc/passwd\tx\tx\tx\t1\tMALE\n")
    rows = fleurs.parse_tsv(tsv)
    assert list(rows) == ["4967621184651376579.wav"] and rows["4967621184651376579.wav"]["text"] == "raw text"


def _riff(tag, bits, payload, rate=16000):
    fmt = struct.pack("<HHIIHH", tag, 1, rate, rate * bits // 8, bits // 8, bits)
    return b"RIFF" + struct.pack("<I", 36 + len(payload)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + \
        b"data" + struct.pack("<I", len(payload)) + payload


def test_read_riff_float_and_pcm16():
    f = np.array([0.5, -0.25], dtype="<f4")
    assert np.allclose(fleurs.read_riff(_riff(3, 32, f.tobytes())), f)
    i = np.array([16384, -8192], dtype="<i2")
    assert np.allclose(fleurs.read_riff(_riff(1, 16, i.tobytes())), [0.5, -0.25])
    with pytest.raises(ValueError):
        fleurs.read_riff(_riff(3, 32, f.tobytes(), rate=48000))


def test_scenarios_use_same_room_noise_before_and_after_speech():
    rng = np.random.default_rng(1)
    pre = (rng.standard_normal(8000) * 0.001).astype(np.float32)
    t = np.arange(16000 * 3) / 16000
    clean = np.concatenate([pre, (0.4 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), pre])
    audio, (start, end) = fleurs.scenario(clean, "normal", np.random.default_rng(2))
    lead = fleurs.frame_rms(audio[: int(0.7 * 16000)])
    tail = fleurs.frame_rms(audio[int((end + 0.5) * 16000):])
    assert 0.5 < np.median(tail) / np.median(lead) < 2.0      # bir xona — bir xil fon
    assert 0.7 < start < 1.2 and 3.5 < end < 4.2
    s_audio, (_s, s_end) = fleurs.scenario(clean, "short_immediate", np.random.default_rng(2))
    assert s_end - _s <= fleurs.SHORT_S + 0.01
