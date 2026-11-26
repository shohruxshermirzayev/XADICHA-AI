"""STT taqqoslash: Gemini Transcribe va Whisper — AYNAN bir xil audio namunalarda.

  cd backend && source .venv/bin/activate
  python -m xadicha.validation.stt_compare                     # to'liq to'plam, ikkala provayder
  python -m xadicha.validation.stt_compare --limit 10          # tez sinov
  python -m xadicha.validation.stt_compare --providers whisper # faqat lokal

Audio — SINTETIK (edge-tts neyron ovozlari: uz Madina/Sardor, ru Svetlana/Dmitry, en Jenny/Guy), odam yozuvi EMAS.
Natijalar real mikrofon va real foydalanuvchi nutqidagi aniqlikni ifodalamaydi — bu ikki provayderni bir xil,
qayta takrorlanadigan sharoitda solishtirish uchun. Audio backend/data/stt_eval/ da (git'ga qo'shilmaydi).

O'lchanadi: WER, CER, o'zbek uchun yozuvdan qat'i nazar WER (kirill → lotin), tilni aniqlash aniqligi, intent
aniqligi (router: matndan bir xil buyruq chiqadimi), kechikish (ms), xato darajasi, jimlikda "o'ylab topish".
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

BACKEND = Path(__file__).resolve().parents[2]
DATASETS = [BACKEND / "validation" / "speech_validation_set.csv", BACKEND / "validation" / "stt_mixed_set.csv"]
AUDIO_DIR = BACKEND / "data" / "stt_eval" / "audio"
VOICES = {"uz": ["uz-UZ-MadinaNeural", "uz-UZ-SardorNeural"], "ru": ["ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"],
          "en": ["en-US-JennyNeural", "en-US-GuyNeural"]}

_UZ_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "ъ": "'", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ё": "yo", "ў": "o'", "қ": "q", "ғ": "g'",
    "ҳ": "h", "щ": "sh", "ы": "i",
}


def uz_latin(text: str) -> str:
    """O'zbek kirill → lotin (taqqoslash uchun; "е" so'z boshida "ye")."""
    out, prev = [], " "
    for ch in text:
        low = ch.lower()
        if low == "е":
            rep = "ye" if not prev.isalpha() else "e"
        else:
            rep = _UZ_CYR.get(low, ch)
        out.append(rep.capitalize() if ch.isupper() and rep else rep)
        prev = ch
    return "".join(out)


def load_items(limit: int | None = None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for path in DATASETS:
        if path.exists():
            with path.open(encoding="utf-8") as f:
                items += list(csv.DictReader(f))
    return items[:limit] if limit else items


def synth(item: dict[str, str], voice_idx: int) -> np.ndarray:
    """Namuna audiosi (16 kHz float32). Keshlanadi — qayta ishga tushirishda bir xil audio ishlatiladi."""
    from ..redaction import safe_env

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    if item["kind"] == "silence":
        wav = AUDIO_DIR / f"{item['id']}-noise.wav"
        if not wav.exists():
            # Past darajali shovqin (nutq yo'q) — "jimlikda matn to'qish"ni o'lchash uchun
            rng = np.random.default_rng(int.from_bytes(item["id"].encode(), "little") % 2**32)
            _write_wav(wav, rng.normal(0, 0.002, 16000 * 2).clip(-1, 1).astype(np.float32))
    else:
        voice = VOICES[item["lang"]][voice_idx % 2]
        wav = AUDIO_DIR / f"{item['id']}-{voice}.wav"
        # edge-tts o'zbek ovozi kirill yozuvini o'qimaydi — bir xil nutq uchun lotin matni (referens kirillda qoladi)
        text = uz_latin(item["text"]) if item["lang"] == "uz" and item.get("script") == "cyrl" else item["text"]
        if not wav.exists():
            mp3 = wav.with_suffix(".mp3")
            edge = Path(sys.executable).with_name("edge-tts")
            src = None
            for _ in range(3):
                r = subprocess.run([str(edge), "--voice", voice, "--text", text, "--write-media", str(mp3)],
                                   capture_output=True, text=True, env=safe_env(), timeout=90)
                if r.returncode == 0 and mp3.exists() and mp3.stat().st_size:
                    src = mp3
                    break
                time.sleep(2.0)
            if src is None and item["lang"] in ("ru", "en"):   # zaxira: macOS tizim ovozi
                src = wav.with_suffix(".aiff")
                subprocess.run(["say", "-v", {"ru": "Milena", "en": "Samantha"}[item["lang"]], "-o", str(src), text],
                               check=True, capture_output=True, env=safe_env(), timeout=60)
            if src is None:
                raise RuntimeError(f"TTS ishlamadi: {item['id']} ({voice})")
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(src), str(wav)],
                           check=True, capture_output=True, env=safe_env(), timeout=60)
            src.unlink(missing_ok=True)
    with wave.open(str(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def _write_wav(path: Path, audio: np.ndarray) -> None:
    from ..speech.recognizer import wav_bytes

    path.write_bytes(wav_bytes(audio))


def intent_of(text: str, lang: str) -> str:
    from ..router import route

    if not text.strip():
        return "—"
    r = route(text, lang)
    act = r.actions[0].describe() if r.actions else ""
    return f"{r.path}:{r.intent}:{act}".lower()


def score(item: dict[str, str], hyp: str, lang_out: str) -> dict[str, Any]:
    from ..metrics import cer, wer

    ref = item["text"]
    if item["kind"] == "silence":
        return {"wer": None, "cer": None, "wer_script": None, "lang_ok": None, "intent_ok": None,
                "hallucination": bool(hyp.strip())}
    ws = None
    if item["lang"] == "uz":
        ws = wer(uz_latin(ref), uz_latin(hyp))
    exp_lang = item["lang"]
    return {"wer": wer(ref, hyp), "cer": cer(ref, hyp), "wer_script": ws, "lang_ok": lang_out == exp_lang,
            "intent_ok": intent_of(ref, exp_lang) == intent_of(hyp, exp_lang), "hallucination": False}


class _DirectGemini:
    """Taqqoslash uchun: Gemini Transcribe zaxirasiz (Whisper'ga o'tmaydi). Bepul tarif limitlari uchun pauza va
    429 da kutib qayta urinish (cheklangan). Muvaffaqiyatsiz bo'lsa — xato sifatida yoziladi, Whisper natijasi emas."""

    def __init__(self, g: Any, vocab: Any, delay_s: float):
        self.g, self.vocab, self.delay_s = g, vocab, delay_s
        self.gemini = g
        self._last = 0.0

    def transcribe(self, audio: np.ndarray, language: str | None = None, prior: str | None = None) -> Any:
        from ..lang import detect_text_language
        from ..providers.base import ProviderError
        from ..speech.recognizer import is_silence
        from ..speech.stt import Transcript

        if is_silence(audio):
            return Transcript("", "", 0.0, True, provider="gemini", model=self.g.model)
        for attempt in range(4):
            wait = self.delay_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                text = self.vocab.correct(self.g.transcribe(audio, language, self.vocab))
                break
            except ProviderError as e:
                if e.kind == "quota" and attempt < 3:
                    print(f"    429 — {30 * (attempt + 1)} s kutish")
                    time.sleep(30 * (attempt + 1))
                    continue
                raise
        guess = detect_text_language(text, prior or "uz") if text else None
        lang = guess.lang if guess else (prior or "uz")
        return Transcript(text, lang, float(guess.confidence) if guess else 0.0, True, provider="gemini",
                          model=self.g.model)


def run(providers: list[str], limit: int | None, voices: int, prior: str | None, out_dir: Path,
        gemini_delay: float = 6.0) -> dict[str, Any]:
    from ..config import load_config
    from ..speech.recognizer import GeminiTranscriber, SpeechRecognizer, Vocabulary, make_recognizer  # noqa: F401
    from ..speech.stt import Listener

    cfg = load_config()
    listener = Listener(cfg.whisper_model, cfg.stt_engine)
    recs: dict[str, SpeechRecognizer] = {}
    if "whisper" in providers:
        recs["whisper"] = SpeechRecognizer(listener, None, "whisper", Vocabulary())
    if "gemini" in providers:
        if not cfg.gemini_api_key:
            print("GEMINI_API_KEY yo'q — Gemini o'lchanmaydi (pending).")
        else:
            g = GeminiTranscriber(cfg.gemini_api_key, cfg.gemini_stt_model, 60)
            recs["gemini"] = _DirectGemini(g, make_recognizer(cfg, listener).vocabulary, gemini_delay)   # zaxirasiz
    items = load_items(limit)
    rows: list[dict[str, Any]] = []
    for vi in range(voices):
        for it in items:
            try:
                audio = synth(it, vi)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {it['id']}: audio yo'q ({e})")
                continue
            for name, rec in recs.items():
                t0 = time.perf_counter()
                err = ""
                try:
                    t = rec.transcribe(audio, None, prior=prior)
                    hyp, lang_out, used = t.text, t.language, t.provider
                except Exception as e:  # noqa: BLE001
                    hyp, lang_out, used, err = "", "", name, f"{e.__class__.__name__}: {e}"[:160]
                ms = int((time.perf_counter() - t0) * 1000)
                s = score(it, hyp, lang_out)
                rows.append({"id": it["id"], "voice": VOICES[it["lang"]][vi % 2], "lang": it["lang"],
                             "script": it.get("script", ""), "kind": it["kind"], "provider": name, "used": used,
                             "ref": it["text"], "hyp": hyp, "lang_out": lang_out, "ms": ms, "error": err, **s})
                mark = "✓" if (s["wer"] == 0 or (it["kind"] == "silence" and not s["hallucination"])) else " "
                print(f"  {mark} {name:7} {it['id']:12} {ms:6}ms  WER={s['wer'] if s['wer'] is None else round(s['wer'], 2)}"
                      f"  {hyp[:60]!r}")
    summary = summarize(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"date": datetime.now().isoformat(timespec="seconds"), "audio": "synthetic edge-tts (not human speech)",
            "providers": {k: (v.gemini.model if k == "gemini" else f"{listener.engine}:{cfg.whisper_model}")
                          for k, v in recs.items()}, "prior_language": prior, "voices_per_item": voices,
            "items": len(items)}
    (out_dir / "results.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "rows.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    (out_dir / "REPORT.md").write_text(report_md(meta, summary), encoding="utf-8")
    return {"meta": meta, "summary": summary}


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for prov in sorted({r["provider"] for r in rows}):
        pr = [r for r in rows if r["provider"] == prov]
        attempted = [r for r in pr if r["kind"] != "silence"]
        speech = [r for r in attempted if not r["error"]]   # muvaffaqiyatli javoblar — aniqlik shulardan
        groups: dict[str, Any] = {}
        for key in sorted({f"{r['lang']}-{r['script']}" for r in speech}):
            g = [r for r in speech if f"{r['lang']}-{r['script']}" == key]
            groups[key] = {"n": len(g), "wer": _mean([r["wer"] for r in g]), "cer": _mean([r["cer"] for r in g]),
                           "wer_script": _mean([r["wer_script"] for r in g]),
                           "lang_acc": _mean([float(r["lang_ok"]) for r in g]),
                           "intent_acc": _mean([float(r["intent_ok"]) for r in g])}
        sil = [r for r in pr if r["kind"] == "silence"]
        lat = sorted(r["ms"] for r in speech)
        out[prov] = {
            "n": len(speech), "wer": _mean([r["wer"] for r in speech]), "cer": _mean([r["cer"] for r in speech]),
            "wer_uz_script_insensitive": _mean([r["wer_script"] for r in speech if r["lang"] == "uz"]),
            "word_acc": _mean([max(0.0, 1 - r["wer"]) for r in speech]),
            "lang_acc": _mean([float(r["lang_ok"]) for r in speech]),
            "intent_acc": _mean([float(r["intent_ok"]) for r in speech]),
            "latency_ms_median": lat[len(lat) // 2] if lat else None,
            "latency_ms_p90": lat[int(len(lat) * 0.9)] if lat else None,
            "attempted": len(attempted),
            "failure_rate": _mean([float(bool(r["error"]) or not r["hyp"].strip()) for r in attempted]),
            "errors": sum(1 for r in attempted if r["error"]),
            "silence_hallucination_rate": _mean([float(r["hallucination"]) for r in sil]) if sil else None,
            "by_group": groups,
        }
    return out


def report_md(meta: dict[str, Any], summary: dict[str, Any]) -> str:
    def f(x, pct=False):
        if x is None:
            return "—"
        return f"{x * 100:.1f}%" if pct else str(x)

    lines = [f"# STT taqqoslash — {meta['date']}", "",
             "**Audio: sintetik (edge-tts neyron ovozlari), odam nutqi emas.** Real mikrofon aniqligi alohida o'lchanadi.",
             f"Namunalar: {meta['items']} × {meta['voices_per_item']} ovoz · til prior: `{meta['prior_language']}` · "
             f"provayderlar: {', '.join(f'{k} ({v})' for k, v in meta['providers'].items())}", "",
             "| Ko'rsatkich | " + " | ".join(summary) + " |", "|---|" + "---|" * len(summary)]
    rows = [("WER", "wer", True), ("CER", "cer", True), ("WER (uz, yozuvdan qat'i nazar)", "wer_uz_script_insensitive", True),
            ("So'z aniqligi (1−WER)", "word_acc", True), ("Til aniqlash", "lang_acc", True),
            ("Intent aniqligi", "intent_acc", True), ("Kechikish, mediana (ms)", "latency_ms_median", False),
            ("Kechikish, p90 (ms)", "latency_ms_p90", False), ("Urinishlar", "attempted", False),
            ("API xatosi (aniqlikka kirmagan)", "errors", False), ("Xato/bo'sh natija", "failure_rate", True),
            ("Jimlikda matn to'qish", "silence_hallucination_rate", True)]
    for label, key, pct in rows:
        lines.append(f"| {label} | " + " | ".join(f(summary[p].get(key), pct) for p in summary) + " |")
    lines += ["", "## Guruhlar bo'yicha (til-yozuv)", ""]
    for p, s in summary.items():
        lines.append(f"**{p}**")
        lines.append("")
        lines.append("| Guruh | n | WER | CER | WER (yozuvsiz) | Til | Intent |")
        lines.append("|---|---|---|---|---|---|---|")
        for g, v in s["by_group"].items():
            lines.append(f"| {g} | {v['n']} | {f(v['wer'], True)} | {f(v['cer'], True)} | {f(v['wer_script'], True)} | "
                         f"{f(v['lang_acc'], True)} | {f(v['intent_acc'], True)} |")
        lines.append("")
    lines += ["Gemini taqqoslashda zaxirasiz chaqiriladi (Whisper'ga o'tmaydi); API xatosi bergan namuna aniqlik",
              "metrikalariga kirmaydi, faqat xato darajasida hisoblanadi. O'zbek kirill namunalari sintez uchun lotinga",
              "o'girilgan (bir xil nutq); referens kirillda — shuning uchun yozuvdan qat'i nazar WER alohida berilgan.",
              "Intent aniqligi: router mos yozuv (referens) va natijadan bir xil yo'l/intent/harakat chiqaradimi.",
              "Til aniqlash: Gemini tilni matndan aniqlaydi (`detect_text_language`), Whisper — o'z ehtimolliklaridan."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stt_compare")
    ap.add_argument("--providers", default="gemini,whisper")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--voices", type=int, default=1, choices=[1, 2])
    ap.add_argument("--prior", default="uz", help="interfeysda tanlangan til (uz/ru/en) yoki 'none'")
    ap.add_argument("--out", default="")
    ap.add_argument("--gemini-delay", type=float, default=6.0, help="Gemini so'rovlari orasidagi pauza (bepul tarif limiti)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else BACKEND / "validation" / "results" / f"stt_compare-{datetime.now():%Y%m%d-%H%M}"
    res = run([p.strip() for p in a.providers.split(",") if p.strip()], a.limit, a.voices,
              None if a.prior == "none" else a.prior, out, a.gemini_delay)
    print(json.dumps(res["summary"], ensure_ascii=False, indent=2)[:3000])
    print(f"\nHisobot: {out / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
