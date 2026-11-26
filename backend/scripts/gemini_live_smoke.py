"""HAQIQIY Gemini Live smoke testi — `LiveSession` klassi real WebSocket bilan (internet + GEMINI_API_KEY kerak).

  cd backend && source .venv/bin/activate
  python scripts/gemini_live_smoke.py            # uz/ru/en suhbat, tool chaqiruvi, barge-in
  python scripts/gemini_live_smoke.py --json out.json

Mikrofon o'rniga SINTETIK nutq (edge-tts, keyin 16 kHz PCM) real vaqt tezligida (32 ms bo'laklar) uzatiladi;
model ovozi karnayga emas, xotiraga yig'iladi. Bu real mikrofon sinovi EMAS — u alohida, foydalanuvchi bilan qilinadi.
Desktop buyrug'i bu sinovda bajarilmaydi (soxta run_command — natija "sinov" deb belgilanadi).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xadicha.config import load_config  # noqa: E402
from xadicha.redaction import redact, safe_env  # noqa: E402
from xadicha.speech.live import CHUNK_MS, IN_RATE, OUT_RATE, LiveSession  # noqa: E402

VOICES = {"uz": "uz-UZ-MadinaNeural", "ru": "ru-RU-SvetlanaNeural", "en": "en-US-JennyNeural"}


def speech_pcm(text: str, lang: str, tmp: Path) -> bytes:
    """edge-tts → MP3 → afconvert (macOS) → 16 kHz mono 16-bit PCM."""
    mp3, wav = tmp / f"{lang}-{abs(hash(text))}.mp3", tmp / f"{lang}-{abs(hash(text))}.wav"
    edge = Path(sys.executable).with_name("edge-tts")
    src = None
    for _ in range(2):
        r = subprocess.run([str(edge), "--voice", VOICES[lang], "--text", text, "--write-media", str(mp3)],
                           capture_output=True, text=True, env=safe_env(), timeout=60)
        if r.returncode == 0 and mp3.exists() and mp3.stat().st_size > 0:
            src = mp3
            break
        time.sleep(1.0)
    if src is None and lang in ("ru", "en"):   # zaxira: macOS tizim ovozi
        aiff = tmp / f"{lang}-{abs(hash(text))}.aiff"
        subprocess.run(["say", "-v", {"ru": "Milena", "en": "Samantha"}[lang], "-o", str(aiff), text],
                       check=True, capture_output=True, env=safe_env(), timeout=60)
        src = aiff
    if src is None:
        raise RuntimeError(f"edge-tts ishlamadi ({lang}): {(r.stderr or '').strip()[-200:]}")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{IN_RATE}", "-c", "1", str(src), str(wav)],
                   check=True, capture_output=True, env=safe_env(), timeout=60)
    import wave

    with wave.open(str(wav)) as w:
        return w.readframes(w.getnframes())


class ScriptedAudio:
    """Mikrofon o'rnida: nutq bo'laklarini real vaqtda uzatadi, keyin jimlik. Model ovozini yig'adi."""

    def __init__(self, utterances: list[bytes], second_when=None):
        self.utterances, self.second_when = utterances, second_when
        self.received = bytearray()
        self.cleared = 0
        self._stop = threading.Event()

    def start(self, on_chunk):
        step = IN_RATE * CHUNK_MS // 1000 * 2

        def feed(pcm: bytes):
            for i in range(0, len(pcm), step):
                if self._stop.is_set():
                    return
                on_chunk(pcm[i:i + step].ljust(step, b"\x00"))
                time.sleep(CHUNK_MS / 1000)

        def run():
            time.sleep(0.5)   # ulanish o'rnatilsin
            feed(self.utterances[0])
            silence = b"\x00" * step
            t_end = time.time() + 60
            sent_second = len(self.utterances) < 2
            while not self._stop.is_set() and time.time() < t_end:
                if not sent_second and self.second_when and self.second_when():
                    feed(self.utterances[1])   # model gapirayotganda gapiramiz (barge-in)
                    sent_second = True
                    continue
                on_chunk(silence)
                time.sleep(CHUNK_MS / 1000)

        threading.Thread(target=run, daemon=True).start()

    def play(self, pcm: bytes):
        self.received.extend(pcm)

    def clear(self):
        self.cleared += 1

    @property
    def playing(self):
        return False

    def stop(self):
        self._stop.set()


def run_case(cfg, name: str, utterances: list[bytes], want: str, barge: bool = False, timeout: float = 45.0) -> dict:
    events: list[dict] = []
    tool_calls: list[str] = []
    holder: dict = {}

    def run_command(instr: str) -> dict:
        tool_calls.append(instr)
        return {"status": "success", "result": "(SINOV) buyruq qabul qilindi; haqiqiy amal bajarilmadi."}

    def speaking_now():
        s = holder.get("s")
        return s is not None and s.state == "speaking" and len(holder["a"].received) > OUT_RATE   # >0.5 s ovoz

    audio = ScriptedAudio(utterances, speaking_now if barge else None)
    holder["a"] = audio
    s = LiveSession(cfg.gemini_api_key, cfg.live_model, events.append, run_command=run_command,
                    audio_factory=lambda: audio, max_reconnects=1)
    holder["s"] = s
    t0 = time.perf_counter()
    s.start()
    end = time.time() + timeout

    def done():
        st = [e.get("state") for e in events if e["type"] == "live_state"]
        if "error" in st:
            return True
        if want == "turn":
            return any(e["type"] == "live_turn" for e in events)
        if want == "tool":
            return bool(tool_calls) and any(e["type"] == "live_turn" for e in events)
        if want == "interrupt":
            return "interrupted" in st and any(e["type"] == "live_turn" for e in events)
        return False

    while time.time() < end and not done():
        time.sleep(0.05)
    s.stop()
    states = [e.get("state") for e in events if e["type"] == "live_state"]
    turns = [e for e in events if e["type"] == "live_turn"]
    ok = done() and "error" not in states
    return {
        "case": name, "ok": ok, "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "states": list(dict.fromkeys(states)), "error": redact(s.error)[:200],
        "user_transcript": turns[0]["user"] if turns else "", "assistant_transcript": turns[0]["assistant"] if turns else "",
        "audio_out_s": round(len(audio.received) / 2 / OUT_RATE, 2), "first_audio_ms": s.first_audio_ms,
        "tool_calls": tool_calls, "interrupt_clears": audio.cleared,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    cfg = load_config()
    print(f"Live model={cfg.live_model}  GEMINI_API_KEY={'o`rnatilgan' if cfg.gemini_api_key else 'YO`Q'}")
    if not cfg.gemini_api_key:
        print("GEMINI_API_KEY yo'q — haqiqiy Live sinovi bajarilmadi.")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="xadicha-live-"))
    cases = [
        ("uz suhbat", [speech_pcm("Salom Xadicha! Qalaysan? Bir gap bilan javob ber.", "uz", tmp)], "turn", False),
        ("ru suhbat", [speech_pcm("Привет! Как дела? Ответь одним предложением.", "ru", tmp)], "turn", False),
        ("en suhbat", [speech_pcm("Hi Xadicha, what can you do? Answer in one sentence.", "en", tmp)], "turn", False),
        ("tool: Safari ni och", [speech_pcm("Xadicha, Safari ni och.", "uz", tmp)], "tool", False),
        ("barge-in", [speech_pcm("Menga O'zbekiston tarixi haqida batafsil gapirib ber.", "uz", tmp),
                      speech_pcm("To'xta! Bas, rahmat.", "uz", tmp)], "interrupt", True),
    ]
    results = []
    for name, utts, want, barge in cases:
        r = run_case(cfg, name, utts, want, barge)
        results.append(r)
        print(f"{'✅' if r['ok'] else '❌'} {name}  ({r['elapsed_ms']} ms)")
        for k in ("states", "user_transcript", "assistant_transcript", "audio_out_s", "first_audio_ms", "tool_calls",
                  "interrupt_clears", "error"):
            if r.get(k) not in (None, "", [], 0):
                print(f"     {k}: {r[k]}")
    passed = sum(r["ok"] for r in results)
    print(f"\n{passed}/{len(results)} holat muvaffaqiyatli (HAQIQIY Live API, sintetik nutq).")
    if args.json:
        Path(args.json).write_text(json.dumps({"model": cfg.live_model, "results": results}, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
