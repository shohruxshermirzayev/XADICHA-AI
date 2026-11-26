"""HAQIQIY ovoz kechikishi benchmark'i: eski (VAD → butun audio → STT) va yangi (oqimli Live Transcription) zanjir.

  cd backend && source .venv/bin/activate
  python scripts/voice_latency_bench.py                 # sintetik audio (fayldan, real vaqt tezligida)
  python scripts/voice_latency_bench.py --mic --n 3     # REAL MIKROFON: audio karnaydan ijro etiladi, mikrofon yozadi
  python scripts/voice_latency_bench.py --json out.json

Har bir so'rovda mikrofon (yoki fayl) boshidan o'lchanadi: birinchi oraliq matn, yakuniy matn, intent, birinchi amal,
amal tugashi, javob matni, birinchi javob ovozi (edge-tts birinchi bo'lagi tayyor). Amallar DryRunAdapter'da —
kompyuterda hech narsa bajarilmaydi. Natijalar haqiqiy API o'lchovi; audio — sintetik TTS (odam nutqi emas).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xadicha.adapters.base import DryRunAdapter  # noqa: E402
from xadicha.agent import Agent  # noqa: E402
from xadicha.config import load_config  # noqa: E402
from xadicha.models import Mode  # noqa: E402
from xadicha.redaction import redact, safe_env  # noqa: E402
from xadicha.speech.stt import SAMPLE_RATE, Endpointer  # noqa: E402
from xadicha.speech.stream import CHUNK_MS, MicSource, StreamingTranscriber  # noqa: E402

AUDIO = Path(__file__).resolve().parent.parent / "data" / "stt_eval" / "audio"
USE_CACHE = True
SAMPLES = [  # (fayl, referens, til) — tezkor yo'l buyruqlari
    ("v_uzl_01-uz-UZ-MadinaNeural", "Kalkulyatorni ishga tushir", "uz"),
    ("v_uzl_02-uz-UZ-MadinaNeural", "Notes ilovasini ochib ber", "uz"),
    ("v_uzl_04-uz-UZ-MadinaNeural", "Telegramni ochib qo'y", "uz"),
    ("v_uzl_05-uz-UZ-MadinaNeural", "", "uz"),
    ("v_uzl_06-uz-UZ-MadinaNeural", "", "uz"),
    ("v_ru_02-ru-RU-SvetlanaNeural", "Запусти Finder", "ru"),
    ("v_ru_03-ru-RU-SvetlanaNeural", "", "ru"),
    ("v_en_01-en-US-JennyNeural", "", "en"),
    ("v_en_02-en-US-JennyNeural", "Launch Finder", "en"),
    ("v_en_03-en-US-JennyNeural", "", "en"),
]


def load_pcm(name: str) -> bytes:
    with wave.open(str(AUDIO / f"{name}.wav")) as w:
        return w.readframes(w.getnframes())


class FileSource:
    """Mikrofon o'rnida: fayl bo'laklari real vaqtda, keyin jimlik (real mikrofon kabi uzilmaydi)."""

    def __init__(self, pcm: bytes, lead_s: float = 0.3):
        self.pcm, self.lead_s, self._stop = pcm, lead_s, threading.Event()
        self.speech_end_at: float | None = None

    def start(self, on_chunk):
        step = SAMPLE_RATE * CHUNK_MS // 1000 * 2
        silence = b"\x00" * step

        def run():
            for _ in range(int(self.lead_s * 1000 / CHUNK_MS)):
                on_chunk(silence)
                time.sleep(CHUNK_MS / 1000)
            for i in range(0, len(self.pcm), step):
                if self._stop.is_set():
                    return
                on_chunk(self.pcm[i:i + step].ljust(step, b"\x00"))
                time.sleep(CHUNK_MS / 1000)
            self.speech_end_at = time.perf_counter()
            while not self._stop.is_set():
                on_chunk(silence)
                time.sleep(CHUNK_MS / 1000)
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self._stop.set()


class SpeakerMic:
    """REAL mikrofon: audio karnaydan (afplay) ijro etiladi, mikrofon havodan yozadi."""

    def __init__(self, name: str, device=None):
        self.name, self.mic, self.player = name, MicSource(device), None
        self.speech_end_at: float | None = None
        self.peak = 0.0

    def start(self, on_chunk):
        def chunk(b: bytes):
            pcm = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768
            self.peak = max(self.peak, float(np.abs(pcm).max()) if pcm.size else 0.0)
            on_chunk(b)
        self.mic.start(chunk)

        def play():
            time.sleep(0.3)
            subprocess.run(["afplay", str(AUDIO / f"{self.name}.wav")], env=safe_env(), timeout=30)
            self.speech_end_at = time.perf_counter()
        threading.Thread(target=play, daemon=True).start()

    def stop(self):
        self.mic.stop()


def tts_first_audio_ms(text: str, lang: str) -> int | None:
    """Javobning birinchi ovoz bo'lagi tayyor bo'lguncha (edge-tts; ijro etilmaydi)."""
    import asyncio
    import os
    import tempfile

    import edge_tts

    from xadicha.speech.tts import EDGE_VOICES, speech_chunks, speech_text

    from xadicha.speech import tts as tts_mod

    chunk = (speech_chunks(speech_text(text, lang)) or [""])[0]
    if not chunk:
        return None
    voice = EDGE_VOICES.get(lang, EDGE_VOICES["en"])
    t = time.perf_counter()
    cached = tts_mod.tts_cache_path(voice, 0, chunk) if USE_CACHE else None
    if cached is not None and cached.exists():
        return int((time.perf_counter() - t) * 1000)
    fd, out = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        asyncio.run(edge_tts.Communicate(chunk, voice).save(out))
    except Exception:  # noqa: BLE001
        return None
    ms = int((time.perf_counter() - t) * 1000)
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        os.replace(out, cached)
    return ms


def run_pipeline(cfg, text: str, lang: str, t0: float, marks: dict) -> None:
    """Matndan keyin: intent (router), birinchi amal, amal tugashi, javob matni (DryRunAdapter), javob ovozi."""
    from xadicha.providers.rule_based import RuleBasedProvider
    from xadicha.router import route

    ms = lambda: int((time.perf_counter() - t0) * 1000)  # noqa: E731
    route(text, lang, fast_path=True)
    marks["intent"] = ms()
    cfg.fast_path = True

    def on_event(e):
        if e["type"] == "step_started":
            marks.setdefault("first_action", ms())
        elif e["type"] == "step_finished":
            marks.setdefault("action_done", ms())

    agent = Agent(cfg, RuleBasedProvider(), DryRunAdapter(), on_event=on_event)
    task = agent.run(text, lang, Mode.multimodal)
    marks["response_text"] = ms()
    a = tts_first_audio_ms(task.final_message, lang)
    if a is not None:
        marks["response_audio"] = marks["response_text"] + a
    marks["intent_ok"] = bool(task.steps) and task.status.value == "success"


def new_path(cfg, src_factory, pool=None) -> dict:
    marks: dict = {}
    holder: dict = {}

    def factory():
        holder["src"] = src_factory()
        return holder["src"]

    st = StreamingTranscriber(cfg.gemini_api_key, cfg.gemini_stt_live_model, vocabulary=["Xadicha", "Telegram", "Finder", "Notes"],
                              source_factory=factory, pool=pool)
    t0 = time.perf_counter()
    r = st.run(threading.Event())
    src = holder["src"]
    marks.update({"connected": r.marks.get("connected"), "first_partial": r.marks.get("first_partial"),
                  "final_transcript": r.marks.get("final"), "finalized_by": r.finalized_by, "text": r.text,
                  "error": redact(r.error)[:160], "pooled": bool(r.marks.get("pooled"))})
    if src.speech_end_at:
        marks["speech_end"] = int((src.speech_end_at - t0) * 1000)
    if r.text:
        run_pipeline(cfg, r.text, "uz", t0, marks)
    return marks


def old_path(cfg, listener, pcm: bytes) -> dict:
    """Eski: VAD (0.9 s jimlik) gap tugashini kutadi → butun audio → Whisper (Gemini Transcribe kvotasi tugagan)."""
    marks: dict = {}
    ep = Endpointer()
    step = SAMPLE_RATE * CHUNK_MS // 1000 * 2
    chunks, t0 = [], time.perf_counter()
    stream = [b"\x00" * step] * int(300 / CHUNK_MS) + [pcm[i:i + step].ljust(step, b"\x00") for i in range(0, len(pcm), step)]
    i = 0
    while True:
        b = stream[i] if i < len(stream) else b"\x00" * step
        if i == len(stream):
            marks["speech_end"] = int((time.perf_counter() - t0) * 1000)
        chunks.append(b)
        x = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768
        time.sleep(CHUNK_MS / 1000)
        if ep.feed(float(np.sqrt(np.mean(x * x))), len(x) / SAMPLE_RATE) or i > 400:
            break
        i += 1
    marks["endpoint"] = int((time.perf_counter() - t0) * 1000)
    audio = np.frombuffer(b"".join(chunks), dtype="<i2").astype(np.float32) / 32768
    t = listener.transcribe(audio, None, prior="uz")
    marks["final_transcript"] = int((time.perf_counter() - t0) * 1000)
    marks["text"] = t.text
    if t.text:
        run_pipeline(cfg, t.text, "uz", t0, marks)
    return marks


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return int(xs[lo] + (xs[hi] - xs[lo]) * (k - lo))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=len(SAMPLES))
    ap.add_argument("--mic", action="store_true", help="real mikrofon (karnay → havo → mikrofon)")
    ap.add_argument("--no-old", action="store_true")
    ap.add_argument("--json", default="")
    ap.add_argument("--dataset", action="store_true", help="butun STT to'plami: WER/CER/intent (oqimli zanjir)")
    ap.add_argument("--no-pool", action="store_true", help="oldindan ochilgan sessiyasiz (har buyruqda ulanish)")
    a = ap.parse_args()
    cfg = load_config()
    if not cfg.gemini_api_key:
        print("GEMINI_API_KEY yo'q — haqiqiy sinov bajarilmadi.")
        return 2
    from xadicha.speech import tts as tts_mod

    tts_mod.TTS_CACHE_DIR = cfg.db_path.parent / "tts_cache"
    from xadicha.speech.stt import Listener

    listener = Listener(cfg.whisper_model, cfg.stt_engine)
    pool = None
    if not a.no_pool:
        from google import genai
        from google.genai import types

        from xadicha.speech.stream import LiveSTTPool, stream_config

        pool = LiveSTTPool(genai.Client(api_key=cfg.gemini_api_key, http_options=types.HttpOptions(api_version="v1beta")),
                           cfg.gemini_stt_live_model, lambda: stream_config(["Xadicha", "Telegram", "Finder", "Notes"]))
        time.sleep(2.5)   # birinchi sessiya ochilsin (servisda — ishga tushishda)
    samples = SAMPLES[: a.n]
    refs: dict[str, tuple[str, str]] = {}
    if a.dataset:
        from xadicha.validation.stt_compare import VOICES, load_items, synth

        samples = []
        for it in load_items():
            if it["kind"] == "silence":
                continue
            synth(it, 0)
            name = f"{it['id']}-{VOICES[it['lang']][0]}"
            samples.append((name, it["text"], it["lang"]))
            refs[name] = (it["text"], it["lang"])
        samples = samples[: a.n] if a.n != len(SAMPLES) else samples
    rows = []
    for name, ref, lang in samples:
        if not (AUDIO / f"{name}.wav").exists():
            continue
        pcm = load_pcm(name)
        src = (lambda n=name: SpeakerMic(n, cfg.microphone or None)) if a.mic else (lambda p=pcm: FileSource(p))
        new = new_path(cfg, src, pool)
        if name in refs:
            from xadicha.metrics import cer, wer
            from xadicha.validation.stt_compare import intent_of, uz_latin

            rt, rl = refs[name]
            hyp = new.get("text", "")
            new.update({"ref": rt, "lang": rl, "wer": wer(rt, hyp), "cer": cer(rt, hyp),
                        "wer_script": wer(uz_latin(rt), uz_latin(hyp)) if rl == "uz" else None,
                        "intent_match": intent_of(rt, rl) == intent_of(hyp, rl)})
        row = {"sample": name, "new": new}
        print(f"NEW {name}: partial={new.get('first_partial')} final={new.get('final_transcript')} "
              f"action={new.get('first_action')} audio={new.get('response_audio')} [{new.get('finalized_by')}] {new.get('text', '')[:40]!r}")
        if not a.no_old and not a.mic and not a.dataset:
            old = old_path(cfg, listener, pcm)
            row["old"] = old
            print(f"OLD {name}: endpoint={old.get('endpoint')} final={old.get('final_transcript')} "
                  f"action={old.get('first_action')} audio={old.get('response_audio')} {old.get('text', '')[:40]!r}")
        rows.append(row)
    summary = {}
    for path in ("new", "old"):
        rs = [r[path] for r in rows if path in r]
        if not rs:
            continue
        summary[path] = {}
        for k in ("first_partial", "final_transcript", "intent", "first_action", "response_text", "response_audio"):
            vals = [r.get(k) for r in rs]
            after = [r.get(k) - r["speech_end"] for r in rs if r.get(k) is not None and r.get("speech_end") is not None]
            summary[path][k] = {"p50": pct(vals, 0.5), "p95": pct(vals, 0.95), "after_speech_end_p50": pct(after, 0.5),
                                "after_speech_end_p95": pct(after, 0.95), "n": len([v for v in vals if v is not None])}
        summary[path]["intent_ok"] = sum(1 for r in rs if r.get("intent_ok")) / len(rs)
        if path == "new" and any("wer" in r for r in rs):
            m = lambda k, xs: round(statistics.mean(x[k] for x in xs if x.get(k) is not None), 4) if any(x.get(k) is not None for x in xs) else None  # noqa: E731
            summary[path]["wer"] = m("wer", rs)
            summary[path]["cer"] = m("cer", rs)
            summary[path]["wer_uz_script_insensitive"] = m("wer_script", rs)
            summary[path]["intent_accuracy"] = round(sum(1 for r in rs if r.get("intent_match")) / len(rs), 4)
            summary[path]["by_lang"] = {lg: {"n": len(g), "wer": m("wer", g), "cer": m("cer", g)}
                                        for lg in ("uz", "ru", "en") if (g := [r for r in rs if r.get("lang") == lg])}
        if path == "new":
            summary[path]["pooled"] = sum(1 for r in rs if r.get("pooled"))
            summary[path]["finalized_by"] = {k: sum(1 for r in rs if r.get("finalized_by") == k) for k in ("server", "interim", "empty", "error")}
            if a.mic:
                summary[path]["mic_peak"] = "audio" if rows else None
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps({"mic": a.mic, "summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
