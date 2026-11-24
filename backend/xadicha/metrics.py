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


def norm_words(text: str) -> list[str]:
    return _norm(text).split()


def align(reference: str, hypothesis: str) -> list[tuple[str, str | None, str | None]]:
    """So'zlar bo'yicha tekislash (Levenshtein orqaga yurish): [(op, ref_word, hyp_word)],
    op: "ok" | "sub" | "del" (so'z tushib qolgan) | "ins" (ortiqcha so'z)."""
    ref, hyp = norm_words(reference), norm_words(hypothesis)
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    ops: list[tuple[str, str | None, str | None]] = []
    i, j = n, m
    def similar(a: str, b: str) -> bool:
        return edit_distance(a, b) <= max(len(a), len(b)) / 2

    while i > 0 or j > 0:
        diag = i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1])
        if diag and ref[i - 1] != hyp[j - 1] and not similar(ref[i - 1], hyp[j - 1]) and (
                (i > 0 and d[i][j] == d[i - 1][j] + 1) or (j > 0 and d[i][j] == d[i][j - 1] + 1)):
            diag = False   # teng narxda: o'xshamagan so'zlarni almashtirishdan ko'ra tushib qolish/ortiqcha afzal
        if diag:
            ops.append(("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], None))
            i -= 1
        else:
            ops.append(("ins", None, hyp[j - 1]))
            j -= 1
    return ops[::-1]


def _common_prefix(a: str, b: str) -> int:
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    return k


def asr_error_types(reference: str, hypothesis: str) -> dict[str, list[str]]:
    """ASR xatolari turlari (tahlil uchun, sof funksiya):
    missing_words — tushib qolgan so'zlar; wrong_endings — o'zak bir xil (≥3 harf), qo'shimcha boshqa
    (masalan "safarini" → "safari"); substitutions — boshqa so'z; insertions — ortiqcha so'z;
    cutoff — gap oxiridagi so'z(lar) tushib qolgan (yozish erta to'xtagan bo'lishi mumkin)."""
    ops = align(reference, hypothesis)
    out: dict[str, list[str]] = {"missing_words": [], "wrong_endings": [], "substitutions": [], "insertions": [],
                                 "cutoff": []}
    for op, r, h in ops:
        if op == "del":
            out["missing_words"].append(r or "")
        elif op == "ins":
            out["insertions"].append(h or "")
        elif op == "sub" and r and h:
            if _common_prefix(r, h) >= 3:
                out["wrong_endings"].append(f"{r}→{h}")
            else:
                out["substitutions"].append(f"{r}→{h}")
    tail = []
    for op, r, _h in reversed(ops):
        if op == "del":
            tail.append(r or "")
        elif op == "ins":
            continue
        else:
            break
    if tail and len(tail) < len([o for o in ops if o[0] != "ins"]):
        out["cutoff"] = tail[::-1]
    return out


def percentile(values: list[float], q: float) -> float | None:
    """Oddiy chiziqli interpolyatsiyali percentil (q: 0..100)."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


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
        calls = [r["llm_calls"] for r in rs if isinstance(r.get("llm_calls"), (int, float))]
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
            "model_calls_mean": round(statistics.mean(calls), 2) if calls else None,
            "model_calls_total": sum(calls) if calls else None,
        }

    out: dict[str, Any] = {"overall": block(rows), "by_mode": {}, "by_lang": {}, "by_category": {}}
    for key, field in (("by_mode", "mode"), ("by_lang", "lang"), ("by_category", "category")):
        for v in sorted({str(r.get(field)) for r in rows}):
            out[key][v] = block([r for r in rows if str(r.get(field)) == v])
    return out
