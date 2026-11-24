"""Nutq va til tushunishini baholash (yorliqlangan korpus: benchmark/speech_manifest.csv).

  python -m xadicha.speech_eval --text-only
      Matn bo'yicha: til aniqlash (LID), niyat (marshrut), obyekt (ilova/so'rov) aniqligi.
      Bu ASR'siz — faqat tushunish qatlami; korpus muallif tomonidan tuzilgan (validlik cheklovi).

  python -m xadicha.speech_eval --audio-dir recordings/ --models large-v3-turbo,small --engines mlx,faster
      Audio bo'yicha (fayl nomi: <manifest id>.wav, 16 kHz mono PCM): har model/dvigatel uchun WER, CER, LID,
      niyat aniqligi, transkripsiya vaqti, xotira. Yozuvlarni foydalanuvchi o'zi yozadi — to'qib chiqarilmaydi.

Natija: JSON (stdout) va xom qatorlar (--out JSONL).
"""

from __future__ import annotations

import argparse
import csv
import json
import resource
import sys
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .conversation import Conversation
from .lang import detect_text_language
from .metrics import cer, wer
from .router import route

MANIFEST = Path(__file__).resolve().parent.parent / "benchmark" / "speech_manifest.csv"


def load_manifest(path: Path = MANIFEST) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _context() -> Conversation:
    """Havola ("uni yana och") buyruqlari uchun bir xil, oldindan belgilangan kontekst."""
    c = Conversation()
    c.last_app, c.last_instruction, c.last_lang = "Safari", "Telegram ni och", "uz"
    c.last_results = [{"title": "Python", "url": "https://python.org"}]
    c.last_path = "/tmp/xadicha-eval/Hisobot.pdf"
    return c


def predict(text: str, selected: str) -> dict[str, Any]:
    lang = detect_text_language(text, selected).lang
    r = route(text, lang, _context())
    a = r.actions[0] if r.actions else None
    if r.resolved_from:
        intent = "follow_up"
        entity = {"result_n": "result_1"}.get(r.ref, r.ref)
    elif r.path == "autonomous":
        intent, entity = "autonomous", ""
    elif a is None:
        intent, entity = r.intent or r.path, ""
    elif a.type == "system":
        intent, entity = "system", "+".join(x.control or "" for x in r.actions)
    elif a.type == "open_url" and r.intent == "web_search":
        intent, entity = "browser_search", a.url or ""
    elif a.type == "open_url":
        intent, entity = "open_url", a.url or ""
    elif a.type == "create_folder":
        intent, entity = "create_folder", Path(a.path or "").name
    else:
        intent, entity = a.type, a.app or a.text or a.path or ""
    return {"lang": lang, "intent": intent, "entity": entity, "path": r.path}


def entity_ok(expected: str, got: str) -> bool:
    if not expected:
        return True
    from urllib.parse import unquote_plus

    e = expected.lower()
    g = (unquote_plus(got) if got.startswith("http") else got).lower()
    return e == g or e in g


def text_eval(rows: list[dict[str, str]], selected: str = "uz") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out = []
    for r in rows:
        p = predict(r["text"], selected)
        out.append({**r, "pred_lang": p["lang"], "pred_intent": p["intent"], "pred_entity": p["entity"],
                    "lang_ok": p["lang"] == r["lang"], "intent_ok": p["intent"] == r["intent"],
                    "entity_ok": p["intent"] == r["intent"] and entity_ok(r["entity"], p["entity"])})

    def acc(rs: list[dict[str, Any]], k: str) -> float | None:
        return round(100 * sum(x[k] for x in rs) / len(rs), 1) if rs else None

    summary: dict[str, Any] = {"n": len(out), "selected_language_prior": selected,
                               "lid_accuracy": acc(out, "lang_ok"), "intent_accuracy": acc(out, "intent_ok"),
                               "entity_accuracy": acc(out, "entity_ok"), "by_lang_script": {}}
    for key in sorted({(x["lang"], x["script"]) for x in out}):
        rs = [x for x in out if (x["lang"], x["script"]) == key]
        summary["by_lang_script"]["_".join(key)] = {"n": len(rs), "lid": acc(rs, "lang_ok"),
                                                    "intent": acc(rs, "intent_ok"), "entity": acc(rs, "entity_ok")}
    summary["errors"] = [{"id": x["id"], "text": x["text"], "expected": [x["lang"], x["intent"], x["entity"]],
                          "got": [x["pred_lang"], x["pred_intent"], x["pred_entity"]]}
                         for x in out if not (x["lang_ok"] and x["intent_ok"] and x["entity_ok"])]
    return summary, out


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path.name}: 16 kHz, mono, 16-bit PCM kerak")
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


def audio_eval(rows: list[dict[str, str]], audio_dir: Path, models: list[str], engines: list[str],
               selected: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from .speech.stt import Listener

    by_id = {r["id"]: r for r in rows}
    files = sorted(p for p in audio_dir.glob("*.wav") if p.stem in by_id)
    if not files:
        raise SystemExit(f"{audio_dir} da manifest id'lariga mos .wav fayl yo'q")
    raw, summary = [], {}
    for engine in engines:
        for model in models:
            li = Listener(model, engine)
            t_load = time.perf_counter()
            li.warmup()
            load_s = time.perf_counter() - t_load
            rs = []
            for f in files:
                ref = by_id[f.stem]
                audio = read_wav(f)
                t0 = time.perf_counter()
                tr = li.transcribe(audio, None, prior=selected)
                dt = time.perf_counter() - t0
                p = predict(tr.text, selected) if tr.text else {"lang": tr.language, "intent": "", "entity": ""}
                rows_out = {"id": f.stem, "engine": li.engine, "model": model, "reference": ref["text"],
                            "hypothesis": tr.text, "wer": wer(ref["text"], tr.text), "cer": cer(ref["text"], tr.text),
                            "asr_lang": tr.language, "lang_ok": tr.language == ref["lang"],
                            "intent_ok": p["intent"] == ref["intent"], "asr_confidence": tr.asr_confidence,
                            "seconds": round(dt, 3), "audio_seconds": round(len(audio) / 16000, 2)}
                rs.append(rows_out)
                raw.append(rows_out)
            n = len(rs)
            summary[f"{li.engine}:{model}"] = {
                "n": n, "load_s": round(load_s, 2),
                "wer_mean": round(sum(r["wer"] for r in rs) / n, 3), "cer_mean": round(sum(r["cer"] for r in rs) / n, 3),
                "lid_accuracy": round(100 * sum(r["lang_ok"] for r in rs) / n, 1),
                "intent_accuracy": round(100 * sum(r["intent_ok"] for r in rs) / n, 1),
                "rtf": round(sum(r["seconds"] for r in rs) / max(1e-6, sum(r["audio_seconds"] for r in rs)), 3),
                "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)),
            }
    return summary, raw


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="xadicha.speech_eval")
    ap.add_argument("--text-only", action="store_true")
    ap.add_argument("--audio-dir")
    ap.add_argument("--models", default="large-v3-turbo")
    ap.add_argument("--engines", default="auto")
    ap.add_argument("--selected", default="uz", help="interfeysda tanlangan til (prior)")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    rows = load_manifest()
    if args.audio_dir:
        summary, raw = audio_eval(rows, Path(args.audio_dir), args.models.split(","), args.engines.split(","), args.selected)
        summary = {"kind": "real audio (user recordings)", **summary}
    else:
        summary, raw = text_eval(rows, args.selected)
        summary = {"kind": "text-only (no ASR), author-made corpus", **summary}
    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in raw), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
