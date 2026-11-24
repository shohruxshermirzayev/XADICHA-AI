"""6-qadam: bosqichlar bo'yicha REAL vaqt o'lchovi va eng katta 3 ta "tor joy".

  python -m xadicha.validate profile --label before        # optimallashtirishdan OLDIN
  python -m xadicha.validate profile --label after         # o'zgarishdan keyin (xuddi shu buyruqlar)
  python -m xadicha.validate profile --compare validation/results/profile-A.json validation/results/profile-B.json

Bir xil buyruqlar --repeat marta bajariladi (birinchisi "sovuq" — model yuklanishi bilan, alohida belgilanadi).
Ovoz bosqichlari (VAD, ASR, til, niyat) oxirgi `speech` natijasidan olinadi — real yozuvlar.
Tasdiq so'ralsa avtomatik RAD etiladi (profil xavfli amal bajarmaydi). Ovoz balandligi oxirida tiklanadi.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import is_macos, latest, save_result
from ..metrics import percentile

COMMANDS = [
    {"id": "open_app", "text": "Kalkulyatorni och", "lang": "uz"},
    {"id": "system_volume", "text": "ovozni 30 ga qo'y", "lang": "uz"},
    {"id": "web_search", "text": "Toshkent haqida qidir", "lang": "uz"},
    {"id": "screen_question", "text": "Ekranda nima turganini aytib ber", "lang": "uz"},
]

# Trace bosqichi → so'ralgan toifa
CATEGORY = [
    ("vad_endpoint", "VAD (nutq tugashini sezish)"), ("asr", "ASR"), ("lang_detect", "Til aniqlash"),
    ("understand", "Niyatni aniqlash"), ("route", "Niyatni aniqlash"), ("llm:", "LLM (reja/qaror/xulosa)"),
    ("screen:capture", "Ekran surati"), ("screen:encode", "Ekran surati"), ("screen:ocr", "OCR"),
    ("screen:ax", "Accessibility"), ("verify", "Tekshiruv"), ("exec:", "Amalni bajarish (tekshiruv bilan)"),
    ("tool:", "Vosita (qidiruv/fayl)"), ("tts:synth", "TTS sintez"), ("tts", "TTS ishga tushirish"),
]


def category(stage: str) -> str | None:
    if stage == "screen":
        return None   # umumiy yig'indi — toifalari alohida hisoblanadi
    for prefix, name in CATEGORY:
        if stage == prefix or (prefix.endswith(":") and stage.startswith(prefix)):
            return name
    return stage


def aggregate(spans: list[dict[str, Any]], n_runs: int) -> dict[str, dict[str, Any]]:
    """Bosqichlar statistikasi (sof funksiya): n, median, p90, max, jami va bitta vazifaga o'rtacha ulush."""
    by: dict[str, list[float]] = {}
    for s in spans:
        c = category(s.get("stage", ""))
        if c is not None and isinstance(s.get("ms"), (int, float)):
            by.setdefault(c, []).append(float(s["ms"]))
    return {c: {"n": len(v), "median_ms": round(statistics.median(v)), "p90_ms": round(percentile(v, 90) or 0),
                "max_ms": round(max(v)), "total_ms": round(sum(v)),
                "ms_per_task": round(sum(v) / max(1, n_runs))} for c, v in by.items()}


def bottlenecks(stats: dict[str, dict[str, Any]], k: int = 3) -> list[dict[str, Any]]:
    return [{"stage": c, **s} for c, s in sorted(stats.items(), key=lambda kv: -kv[1]["ms_per_task"])[:k]]


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    a, b = old.get("stages", {}), new.get("stages", {})
    rows = []
    for c in sorted(set(a) | set(b)):
        ma, mb = a.get(c, {}).get("median_ms"), b.get(c, {}).get("median_ms")
        rows.append({"stage": c, "before_median_ms": ma, "after_median_ms": mb,
                     "change_pct": round(100 * (mb - ma) / ma, 1) if ma and mb is not None else None})
    return rows


def voice_spans() -> tuple[list[dict[str, Any]], str | None]:
    sp = latest("speech")
    if not sp or not sp.get("real"):
        return [], None
    spans = []
    for it in sp.get("items", []):
        if it.get("eos_ms") is not None:
            spans.append({"stage": "vad_endpoint", "ms": it["eos_ms"]})
        for k, st in (("asr_ms", "asr"), ("lang_ms", "lang_detect"), ("intent_ms", "understand")):
            if it.get(k) is not None:
                spans.append({"stage": st, "ms": it[k]})
    return spans, sp.get("run_id")


def tts_synth_ms(svc, text: str, lang: str) -> int | None:
    """Javob matnini faylga sintez qilish vaqti (ijro vaqtisiz) — `say -o`."""
    voice = svc.speaker.voice_for(lang)
    if not voice or svc.speaker.engine != "system":
        return None
    from ..speech.tts import speech_text

    with tempfile.TemporaryDirectory() as d:
        t0 = time.perf_counter()
        r = subprocess.run(["say", "-v", voice, "-o", str(Path(d) / "t.aiff"), speech_text(text, lang)],
                           capture_output=True, timeout=60)
        return round((time.perf_counter() - t0) * 1000) if r.returncode == 0 else None


def main(args) -> int:
    if args.compare:
        old, new = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare)
        rows = compare(old, new)
        for r in rows:
            print(f"  {r['stage']:38} {r['before_median_ms']!s:>7} → {r['after_median_ms']!s:>7} ms  ({r['change_pct']}%)")
        path = save_result("profile_compare", {"before": args.compare[0], "after": args.compare[1], "rows": rows,
                                               "real": bool(old.get("real") and new.get("real"))})
        print(f"Saqlandi: {path}")
        return 0
    if not is_macos():
        print("Profil faqat Mac'da (real adapter va model bilan) o'lchanadi.")
        return 2
    from ..config import load_config
    from ..models import Mode
    from ..service import XadichaService
    from . import macprobe

    cfg = load_config()
    svc = XadichaService(cfg)
    svc.agent.confirm = lambda *a: False   # profil xavfli amal bajarmaydi
    vol0 = macprobe.output_volume()
    runs, spans = [], []
    print(f"Provayder: {svc.provider.name} · ASR: {svc.listener.engine} · TTS: {svc.speaker.engine}")
    try:
        for i in range(max(1, args.repeat)):
            if i == 1:
                print("Isitish (warmup) — model va ASR oldindan yuklanadi...")
                t0 = time.perf_counter()
                svc.provider.warmup()
                runs.append({"warmup_ms": round((time.perf_counter() - t0) * 1000)})
            for c in COMMANDS:
                t0 = time.perf_counter()
                task = svc.run_task(c["text"], c["lang"], Mode.multimodal, speak=True)
                total = round((time.perf_counter() - t0) * 1000)
                synth = tts_synth_ms(svc, task.final_message, task.language) if task.final_message else None
                trace = list(task.trace) + ([{"stage": "tts:synth", "ms": synth, "ok": True}] if synth else [])
                rec = {"iteration": i, "cold": i == 0, "command": c["id"], "status": task.status.value,
                       "total_ms": total, "llm_calls": task.llm_calls, "trace": trace}
                runs.append(rec)
                if i > 0:
                    spans.extend(trace)
                print(f"  [{i}] {c['id']:16} {task.status.value:9} {total:6} ms  · " +
                      ", ".join(f"{s['stage']}={s['ms']}" for s in trace))
                time.sleep(0.5)
    finally:
        if vol0 is not None:
            subprocess.run(["osascript", "-e", f"set volume output volume {vol0}"], capture_output=True)
    vs, speech_run = voice_spans()
    warm = [r for r in runs if r.get("iteration", 0) > 0 and "total_ms" in r]
    n_runs = max(1, len(warm))
    stages = aggregate(spans, n_runs)
    voice = aggregate(vs, max(1, sum(1 for s in vs if s["stage"] == "asr")))
    per_cmd = {c["id"]: round(statistics.median([r["total_ms"] for r in warm if r["command"] == c["id"]]))
               for c in COMMANDS if any(r["command"] == c["id"] for r in warm)}
    cold = {r["command"]: r["total_ms"] for r in runs if r.get("cold")}
    data = {"real": True, "label": args.label, "provider": svc.provider.name,
            "model": getattr(svc.provider, "model", None), "stt_engine": svc.listener.engine,
            "repeat": args.repeat, "stages": stages, "voice_stages": voice, "voice_source_run": speech_run,
            "per_command_median_ms": per_cmd, "cold_first_run_ms": cold,
            "bottlenecks_top3": bottlenecks({**stages, **voice}), "runs": runs}
    path = save_result("profile", data)
    print("\nEng katta 3 ta tor joy (bitta vazifaga o'rtacha ms):")
    for b in data["bottlenecks_top3"]:
        print(f"  {b['stage']}: {b['ms_per_task']} ms/vazifa (median {b['median_ms']}, p90 {b['p90_ms']})")
    print(f"Saqlandi: {path}")
    return 0
