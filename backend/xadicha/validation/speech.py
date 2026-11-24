"""2-qadam: real mikrofon va ASR sinovi — ALOHIDA, oldindan ko'rilmagan to'plamda (validation/speech_validation_set.csv).

  python -m xadicha.validate speech                       # hammasini yozish (≈64 ta, har biri bir necha soniya)
  python -m xadicha.validate speech --only uz_latn,mixed  # faqat ba'zi guruhlar
  python -m xadicha.validate speech --rescore validation/results/speech-<vaqt> --models small,large-v3-turbo
      # saqlangan HAQIQIY yozuvlarni boshqa model/dvigatel bilan qayta baholash (mikrofon kerak emas)

O'lchanadi: WER, CER, til aniqlash, niyat va obyekt aniqligi, ASR vaqti, nutq tugashini sezish kechikishi,
xato turlari (tushib qolgan so'z, noto'g'ri qo'shimcha, til chalkashligi, ilova nomi xatosi, kesilish,
jimlikda "eshitilgan" matn). Audio to'qib chiqarilmaydi — faqat siz yozgan ovoz.
127 buyruqli korpus bu yerda ISHLATILMAYDI (u sozlashda ishlatilgan, regressiya testi).
"""

from __future__ import annotations

import csv
import json
import statistics
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from . import RESULTS_DIR, VALIDATION_DIR, is_macos, save_result, stamp
from ..metrics import asr_error_types, cer, percentile, wer

SET_FILE = VALIDATION_DIR / "speech_validation_set.csv"
GROUPS = ("uz_latn", "uz_cyrl", "ru", "en", "mixed", "silence")


def load_set(path: Path = SET_FILE) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group_of(row: dict[str, str]) -> str:
    if row["kind"] in ("silence", "mixed"):
        return row["kind"]
    return "uz_" + row["script"] if row["lang"] == "uz" else row["lang"]


def score_item(row: dict[str, str], hyp: str, asr_lang: str, final_lang: str, selected: str) -> dict[str, Any]:
    """Bitta yozuvni baholash (sof funksiya — testlanadi)."""
    from ..speech_eval import entity_ok, predict

    out: dict[str, Any] = {"id": row["id"], "group": group_of(row), "reference": row["text"], "hypothesis": hyp,
                           "asr_lang": asr_lang, "final_lang": final_lang}
    if row["kind"] == "silence":
        out.update(false_transcription=bool(hyp.strip()))
        return out
    t0 = time.perf_counter()
    p = predict(hyp, selected) if hyp.strip() else {"lang": final_lang, "intent": "", "entity": ""}
    out["intent_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    errs = asr_error_types(row["text"], hyp)
    lid_ok = final_lang == row["lang"]
    intent_ok = p["intent"] == row["intent"]
    ent_ok = intent_ok and entity_ok(row["entity"], p["entity"])
    out.update(
        wer=round(wer(row["text"], hyp), 4), cer=round(cer(row["text"], hyp), 4),
        lid_ok=lid_ok, intent_ok=intent_ok, entity_ok=ent_ok,
        expected=[row["lang"], row["intent"], row["entity"]], got=[final_lang, p["intent"], p["entity"]],
        errors={
            **{k: v for k, v in errs.items() if v},
            **({"language_confusion": f"{row['lang']}→{final_lang}"} if not lid_ok else {}),
            **({"app_name": f"{row['entity']}→{p['entity'] or '∅'}"} if row["intent"] == "open_app" and not ent_ok else {}),
            **({"empty_transcript": True} if not hyp.strip() else {}),
        },
    )
    return out


def _mean(xs: list[float]) -> float | None:
    return round(statistics.mean(xs), 4) if xs else None


def _pct(rs: list[dict[str, Any]], k: str) -> float | None:
    vals = [r[k] for r in rs if k in r]
    return round(100 * sum(1 for v in vals if v) / len(vals), 1) if vals else None


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    def block(rs: list[dict[str, Any]]) -> dict[str, Any]:
        cmd = [r for r in rs if r["group"] != "silence"]
        sil = [r for r in rs if r["group"] == "silence"]
        asr = [r["asr_ms"] for r in rs if r.get("asr_ms") is not None]
        eos = [r["eos_ms"] for r in rs if r.get("eos_ms") is not None]
        counts: dict[str, int] = {}
        for r in cmd:
            for k in (r.get("errors") or {}):
                counts[k] = counts.get(k, 0) + 1
        return {
            "n": len(rs), "n_commands": len(cmd),
            "wer_mean": _mean([r["wer"] for r in cmd if "wer" in r]),
            "cer_mean": _mean([r["cer"] for r in cmd if "cer" in r]),
            "lid_accuracy": _pct(cmd, "lid_ok"), "intent_accuracy": _pct(cmd, "intent_ok"),
            "entity_accuracy": _pct(cmd, "entity_ok"),
            "asr_ms_median": round(statistics.median(asr)) if asr else None,
            "asr_ms_p90": round(percentile(asr, 90)) if asr else None,
            "eos_ms_median": round(statistics.median(eos)) if eos else None,
            "eos_ms_p90": round(percentile(eos, 90)) if eos else None,
            "silence_trials": len(sil),
            "silence_false_transcriptions": sum(1 for r in sil if r.get("false_transcription")),
            "error_counts": counts,
        }

    out = {"overall": block(items), "by_group": {}}
    for g in GROUPS:
        rs = [r for r in items if r["group"] == g]
        if rs:
            out["by_group"][g] = block(rs)
    return out


def write_wav(path: Path, audio: np.ndarray, rate: int = 16000) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _transcribe_and_score(li, row, audio, selected: str) -> dict[str, Any]:
    from ..lang import refine_asr_language

    t0 = time.perf_counter()
    tr = li.transcribe(audio, None, prior=selected)
    asr_ms = round((time.perf_counter() - t0) * 1000)
    t1 = time.perf_counter()
    final = refine_asr_language(tr.text, tr.language, tr.probability or None, selected) if tr.text else tr.language
    lang_ms = round((time.perf_counter() - t1) * 1000, 1)
    rec = score_item(row, tr.text, tr.language, final, selected)
    rec.update(asr_ms=asr_ms, lang_ms=lang_ms, asr_confidence=tr.asr_confidence, whisper_raw_lang=tr.detected_raw,
               audio_s=round(len(audio) / 16000, 2), engine=li.engine, model=li.model_name)
    return rec


def record_session(args, cfg) -> int:
    from ..speech.stt import Endpointer, Listener

    rows = load_set()
    only = set(filter(None, (args.only or "").split(",")))
    rows = [r for r in rows if not only or group_of(r) in only]
    if args.limit:
        rows = rows[: args.limit]
    run_id = stamp()
    audio_dir = RESULTS_DIR / f"speech-{run_id}" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    li = Listener(cfg.whisper_model, cfg.stt_engine)
    print(f"ASR: {li.engine} · {cfg.whisper_model}. Model yuklanmoqda (birinchi marta bir necha daqiqa olishi mumkin)...")
    t0 = time.perf_counter()
    li.warmup()
    load_s = round(time.perf_counter() - t0, 2)
    print(f"Yuklandi: {load_s} s.\n")
    print("Har bir qatorda: Enter bosing → 0,5 s jim turing → matnni oddiy ovozda o'qing → jim turing.\n"
          "Yozish o'zi to'xtaydi. 'JIMLIK' qatorlarida hech narsa demang (fon shovqini sinovi).\n"
          "Chiqish: Ctrl+C (shu paytgacha yozilganlar saqlanadi).\n")
    items: list[dict[str, Any]] = []
    meta = {"selected_language_prior": args.selected, "engine": li.engine, "model": cfg.whisper_model,
            "model_load_s": load_s, "set_file": str(SET_FILE.name), "audio_dir": str(audio_dir),
            "kind": "real microphone recordings (user)", "real": True}

    def save() -> Path:
        return save_result("speech", {**meta, "summary": summarize(items), "items": items}, run_id)

    try:
        for i, row in enumerate(rows, 1):
            label = "JIMLIK — hech narsa demang" if row["kind"] == "silence" else row["text"]
            input(f"[{i}/{len(rows)}] {group_of(row):8} «{label}»  — Enter...")
            ep, stop = Endpointer(), threading.Event()
            tr0 = time.perf_counter()
            audio = li.record_until(stop, max_seconds=8 if row["kind"] == "silence" else 15, endpointer=ep)
            cap_ms = round((time.perf_counter() - tr0) * 1000)
            write_wav(audio_dir / f"{row['id']}.wav", audio)
            rec = _transcribe_and_score(li, row, audio, args.selected)
            rec.update(capture_ms=cap_ms, vad_reason=ep.reason or "max_seconds",
                       eos_ms=round(ep.endpoint_delay_s * 1000) if ep.reason == "silence" else None,
                       speech_s=round(ep.speech_total, 2), noise_floor=round(ep.floor or 0, 5))
            if row["kind"] != "silence" and ep.reason != "silence":
                rec.setdefault("errors", {})["vad"] = ep.reason or "max_seconds"
            items.append(rec)
            mark = "✓" if rec.get("intent_ok") or (row["kind"] == "silence" and not rec.get("false_transcription")) else "✗"
            print(f"     {mark} «{rec['hypothesis']}»  WER={rec.get('wer', '-')}  til={rec['final_lang']}  "
                  f"ASR={rec['asr_ms']} ms  EOS={rec['eos_ms']} ms")
            save()
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
    path = save()
    print(json.dumps(summarize(items)["overall"], ensure_ascii=False, indent=2))
    print(f"\nSaqlandi: {path}\nAudio: {audio_dir}")
    return 0


def rescore(args, cfg) -> int:
    """Saqlangan haqiqiy yozuvlarni boshqa model/dvigatel bilan qayta baholash (ASR modellarini solishtirish)."""
    from ..speech.stt import Listener
    from ..speech_eval import read_wav

    run_dir = Path(args.rescore)
    audio_dir = run_dir / "audio" if (run_dir / "audio").exists() else run_dir
    rows = {r["id"]: r for r in load_set()}
    files = sorted(p for p in audio_dir.glob("*.wav") if p.stem in rows)
    if not files:
        print(f"{audio_dir} da yozuv topilmadi.")
        return 2
    comparisons = {}
    for engine in (args.engines or "auto").split(","):
        for model in (args.models or cfg.whisper_model).split(","):
            li = Listener(model, engine)
            t0 = time.perf_counter()
            li.warmup()
            load_s = round(time.perf_counter() - t0, 2)
            items = []
            for f in files:
                audio = read_wav(f)
                items.append(_transcribe_and_score(li, rows[f.stem], audio, args.selected))
            comparisons[f"{li.engine}:{model}"] = {"model_load_s": load_s, "summary": summarize(items), "items": items}
            print(f"{li.engine}:{model}", json.dumps(summarize(items)["overall"], ensure_ascii=False))
    path = save_result("speech_rescore", {"source_audio": str(audio_dir), "selected_language_prior": args.selected,
                                          "real": True, "kind": "re-transcription of real recordings",
                                          "comparisons": comparisons})
    print(f"Saqlandi: {path}")
    return 0


def text_only(args) -> int:
    """Tushunish qatlamini (til, niyat, obyekt) ko'rilmagan to'plamning MATNIDA baholash — ASR'siz.
    Bu real nutq natijasi emas; faqat ASR xatosiz holatdagi yuqori chegara."""
    from ..lang import detect_text_language

    items = []
    for row in load_set():
        if row["kind"] == "silence":
            continue
        lang = detect_text_language(row["text"], args.selected).lang
        items.append(score_item(row, row["text"], lang, lang, args.selected))
    summary = summarize(items)
    path = save_result("speech_text", {"kind": "text-only on held-out set (no ASR, no audio)", "real": False,
                                       "selected_language_prior": args.selected, "summary": summary, "items": items})
    print(json.dumps({k: summary["overall"][k] for k in ("n_commands", "lid_accuracy", "intent_accuracy",
                                                          "entity_accuracy")}, ensure_ascii=False))
    for g, b in summary["by_group"].items():
        print(f"  {g:8} n={b['n_commands']:2}  til={b['lid_accuracy']}  niyat={b['intent_accuracy']}  obyekt={b['entity_accuracy']}")
    errs = [r for r in items if not (r["lid_ok"] and r["intent_ok"] and r["entity_ok"])]
    for r in errs:
        print(f"  ✗ {r['id']}: «{r['reference']}»  kutilgan={r['expected']}  olindi={r['got']}")
    print(f"Saqlandi: {path}")
    return 0


def main(args) -> int:
    from ..config import load_config

    if args.text_only:
        return text_only(args)
    cfg = load_config()
    if args.rescore:
        return rescore(args, cfg)
    if not is_macos():
        print("Mikrofon sinovi faqat Mac'da (real qurilmada) o'tkaziladi.")
        return 2
    return record_session(args, cfg)
