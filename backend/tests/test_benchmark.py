"""Benchmark tizimi va metrikalar (harness tekshiruvi — SIMULYATSIYA, tadqiqot natijasi emas)."""

from __future__ import annotations

import json

import pytest

from xadicha import benchmark as bm
from xadicha.adapters.base import DryRunAdapter
from xadicha.metrics import cer, summarize_runs, wer
from xadicha.providers import RuleBasedProvider


def test_wer_cer_basic():
    assert wer("Safari ni och", "Safari ni och") == 0.0
    assert wer("Safari ni och", "Staffar in och") == pytest.approx(2 / 3)
    assert wer("a b c", "") == 1.0 and wer("", "") == 0.0
    assert cer("salom", "salom") == 0.0
    assert cer("salom", "salam") == pytest.approx(1 / 5)
    assert wer("Safari'ni OCH!", "safari’ni och") == 0.0   # tinish belgisi va apostrof turi hisobga olinmaydi


def test_task_set_is_well_formed():
    tasks = bm.load_tasks()
    assert len(tasks) >= 30
    ids = [t["id"] for t in tasks]
    assert len(set(ids)) == len(ids)
    for t in tasks:
        assert set(t["variants"]) == {"uz", "uz_cyrl", "ru", "en"}, t["id"]
        assert all(v.strip() for v in t["variants"].values())
        assert t["expected"]["type"] in {"frontmost_app", "folder_exists", "file_exists", "url_opened", "not_executed",
                                         "confirm_requested", "answer_only"}
    cats = {t["category"] for t in tasks}
    assert {"open_app", "open_url", "web_search", "create_folder", "multi_step", "safety", "screen_question"} <= cats


def test_summary_metrics_from_rows():
    rows = [
        {"mode": "C", "lang": "uz", "category": "x", "ground_truth_success": True, "claimed_success": True,
         "intent_correct": True, "had_failed_step": True, "latency_ms": 100, "safety_ok": None},
        {"mode": "C", "lang": "ru", "category": "x", "ground_truth_success": False, "claimed_success": True,
         "intent_correct": False, "had_failed_step": True, "latency_ms": 300, "safety_ok": True},
        {"mode": "A", "lang": "uz", "category": "x", "ground_truth_success": None, "claimed_success": True,
         "intent_correct": None, "had_failed_step": False, "latency_ms": 50, "safety_ok": None, "wer": 0.5},
    ]
    s = summarize_runs(rows)
    c = s["by_mode"]["C"]
    assert c["tsr"] == 50.0 and c["intent_accuracy"] == 50.0 and c["verification_accuracy"] == 50.0
    assert c["recovery_success_rate"] == 50.0 and c["latency_ms_median"] == 200 and c["safety_compliance"] == 100.0
    assert s["by_mode"]["A"]["tsr"] is None and s["by_mode"]["A"]["wer_mean"] == 0.5   # tekshirib bo'lmaydi — 0 emas


def test_dry_run_harness_writes_labelled_raw_logs(cfg, tmp_path):
    out = tmp_path / "run.jsonl"
    rows = bm.run(cfg, RuleBasedProvider(), DryRunAdapter(), ["A"], ["uz", "ru"],
                  {"open_calculator", "safety_system", "safety_delete"}, out, simulated=True)
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["meta"]["simulated"] is True
    assert len(rows) == 6 and all(r["simulated"] for r in rows)
    calc = next(r for r in rows if r["task_id"] == "open_calculator" and r["lang"] == "uz")
    assert calc["ground_truth_success"] is True and calc["task"]["steps"][0]["action"]["app"] == "Calculator"
    for r in rows:
        if r["task_id"].startswith("safety"):
            assert r["safety_ok"] is True   # o'chirish hech qachon bajarilmagan


def test_benchmark_confirm_policy_never_approves_high_risk(tmp_path):
    from xadicha.models import Action, RiskLevel, TaskRecord

    log: list = []
    confirm = bm.make_confirm(tmp_path / "xadicha-bench", log)
    t = TaskRecord(instruction="x")
    assert confirm(t, Action(type="delete_path", path=str(tmp_path / "xadicha-bench" / "a")), RiskLevel.high, "") is False
    assert confirm(t, Action(type="create_folder", path=str(tmp_path / "xadicha-bench" / "a")), RiskLevel.medium, "") is True
    assert confirm(t, Action(type="create_folder", path=str(tmp_path / "boshqa")), RiskLevel.medium, "") is False
