"""Baholash metrikalari: WER, CER (Levenshtein), TSR va boshqalar. Sof funksiyalar — testlanadi."""

from __future__ import annotations

import re
import statistics
import unicodedata
from typing import Any


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text.lower())
    t = re.sub(r"[ʻʼ’‘`´]", "'", t)
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def edit_distance(a: list[str] | str, b: list[str] | str) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate = (S + D + I) / N, tinish belgilarisiz va kichik harflarda."""
    ref, hyp = _norm(reference).split(), _norm(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate (bo'shliqlarsiz)."""
    ref, hyp = _norm(reference).replace(" ", ""), _norm(hypothesis).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def _rate(num: int, den: int) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Runner yozgan qatorlardan (har biri bitta vazifa varianti) metrikalarni hisoblaydi.

    Qator maydonlari: mode, lang, category, ground_truth_success (bool|None), claimed_success (bool),
    intent_correct (bool|None), had_failed_step (bool), latency_ms (int), safety_ok (bool|None),
    wer/cer (float|None).
    """
    def block(rs: list[dict[str, Any]]) -> dict[str, Any]:
        gt = [r for r in rs if r.get("ground_truth_success") is not None]
        ok = sum(1 for r in gt if r["ground_truth_success"])
        intent = [r for r in rs if r.get("intent_correct") is not None]
        verif = [r for r in gt if r.get("claimed_success") is not None]
        rec = [r for r in gt if r.get("had_failed_step")]
        safety = [r for r in rs if r.get("safety_ok") is not None]
        lat = [r["latency_ms"] for r in rs if isinstance(r.get("latency_ms"), (int, float))]
        w = [r["wer"] for r in rs if r.get("wer") is not None]
        c = [r["cer"] for r in rs if r.get("cer") is not None]
        return {
            "n": len(rs),
            "tsr": _rate(ok, len(gt)),                                                  # Task Success Rate
            "intent_accuracy": _rate(sum(1 for r in intent if r["intent_correct"]), len(intent)),
            "verification_accuracy": _rate(sum(1 for r in verif if r["claimed_success"] == r["ground_truth_success"]),
                                           len(verif)),
            "recovery_success_rate": _rate(sum(1 for r in rec if r["ground_truth_success"]), len(rec)),
            "safety_compliance": _rate(sum(1 for r in safety if r["safety_ok"]), len(safety)),
            "latency_ms_median": round(statistics.median(lat)) if lat else None,
            "latency_ms_mean": round(statistics.mean(lat)) if lat else None,
            "wer_mean": round(statistics.mean(w), 3) if w else None,
            "cer_mean": round(statistics.mean(c), 3) if c else None,
        }

    out: dict[str, Any] = {"overall": block(rows), "by_mode": {}, "by_lang": {}, "by_category": {}}
    for key, field in (("by_mode", "mode"), ("by_lang", "lang"), ("by_category", "category")):
        for v in sorted({str(r.get(field)) for r in rows}):
            out[key][v] = block([r for r in rows if str(r.get(field)) == v])
    return out
