"""Real validatsiya vositalarining sof qismlari (hisob-kitob, to'plamlar, hisobot). Bular SIMULYATSIYA testlari:
real Mac natijasini isbotlamaydi — faqat o'lchov vositalari to'g'ri hisoblashini tekshiradi."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from xadicha.adapters.base import DryRunAdapter, ExecResult
from xadicha.agent import Agent
from xadicha.config import Config
from xadicha.metrics import align, asr_error_types, percentile, summarize_runs
from xadicha.models import Action, Mode
from xadicha.providers.rule_based import folder_path, parse_command
from xadicha.validation import report, speech
from xadicha.validation.profile import aggregate, bottlenecks, category, compare
from xadicha.validation.search_eval import answer_checks
from xadicha.validation.tts_eval import candidates, phrases_for

from conftest import ScriptedProvider

BACKEND = Path(__file__).resolve().parent.parent


# --- metrikalar ---
def test_align_and_error_types():
    ops = align("Safarini och iltimos", "Safari och")
    assert [o[0] for o in ops] == ["sub", "ok", "del"]
    e = asr_error_types("Safarini och iltimos", "Safari och")
    assert e["wrong_endings"] == ["safarini→safari"]
    assert e["missing_words"] == ["iltimos"] and e["cutoff"] == ["iltimos"]
    assert asr_error_types("ovozni ko'tar", "ovozni ko'tar")["missing_words"] == []
    assert asr_error_types("open notes", "open nodes and")["insertions"] == ["and"]


def test_percentile():
    assert percentile([], 90) is None
    assert percentile([10, 20, 30, 40], 50) == 25
    assert percentile([5], 90) == 5


def test_summarize_runs_counts_model_calls():
    rows = [{"mode": "C", "llm_calls": 2, "latency_ms": 100}, {"mode": "C", "llm_calls": 4, "latency_ms": 300}]
    s = summarize_runs(rows)["by_mode"]["C"]
    assert s["model_calls_mean"] == 3 and s["model_calls_total"] == 6


# --- ko'rilmagan nutq to'plami ---
def _rows(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_validation_set_is_disjoint_from_tuning_corpus():
    held = speech.load_set()
    tuned = {r["text"].strip().lower() for r in _rows(BACKEND / "benchmark" / "speech_manifest.csv")}
    tasks = json.loads((BACKEND / "benchmark" / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    bench = {v.strip().lower() for t in tasks for v in t["variants"].values()}
    texts = [r["text"].strip().lower() for r in held if r["kind"] != "silence"]
    assert not set(texts) & tuned, "ko'rilmagan to'plam sozlash korpusi bilan kesishmasligi kerak"
    assert not set(texts) & bench
    assert len({r["id"] for r in held}) == len(held)


def test_validation_set_labels_are_valid():
    held = speech.load_set()
    intents = {"open_app", "open_url", "browser_search", "web_search", "find_file", "system", "autonomous"}
    groups = {speech.group_of(r) for r in held}
    assert groups == set(speech.GROUPS)
    for r in held:
        if r["kind"] == "silence":
            assert r["text"] == ""
            continue
        assert r["lang"] in ("uz", "ru", "en") and r["intent"] in intents, r
    assert sum(1 for r in held if r["kind"] == "silence") >= 3


def test_score_item_command_and_silence():
    row = {"id": "x", "lang": "ru", "script": "cyrl", "kind": "command", "text": "Открой калькулятор",
           "intent": "open_app", "entity": "Calculator"}
    ok = speech.score_item(row, "Открой калькулятор", "ru", "ru", "uz")
    assert ok["wer"] == 0 and ok["lid_ok"] and ok["intent_ok"] and ok["entity_ok"] and not ok["errors"]
    bad = speech.score_item(row, "открой", "ru", "uz", "uz")
    assert bad["errors"]["language_confusion"] == "ru→uz" and "missing_words" in bad["errors"]
    sil = speech.score_item({"id": "s", "lang": "", "script": "", "kind": "silence", "text": "", "intent": "",
                             "entity": ""}, "Thank you.", "en", "en", "uz")
    assert sil["false_transcription"] is True
    s = speech.summarize([ok, bad, sil])
    assert s["overall"]["silence_false_transcriptions"] == 1 and s["overall"]["n_commands"] == 2


def test_write_and_read_wav(tmp_path):
    import numpy as np

    from xadicha.speech_eval import read_wav

    p = tmp_path / "a.wav"
    speech.write_wav(p, np.zeros(8000, dtype=np.float32))
    assert read_wav(p).shape == (8000,)


# --- qidiruv javobi tekshiruvi ---
def test_answer_checks_flags_invented_url_and_bad_citation():
    res = [{"title": "Samarqand — Vikipediya", "url": "https://uz.wikipedia.org/wiki/Samarqand",
            "snippet": "Samarqand qadimiy shahar, miloddan avvalgi VIII asrda"}]
    good = answer_checks("Samarqand qadimiy shahar [1].", res)
    assert good["has_citation"] and good["citations_valid"] and not good["invented_urls"]
    assert good["lexical_support"] == 1.0
    bad = answer_checks("Manba [3]: https://fake.example.com/x", res)
    assert bad["citations_valid"] is False and bad["invented_urls"] == ["https://fake.example.com/x"]


# --- profil ---
def test_profile_aggregate_and_bottlenecks():
    assert category("llm:decide") == category("llm:summarize") == "LLM (reja/qaror/xulosa)"
    assert category("exec:open_app").startswith("Amalni") and category("screen") is None
    assert category("tts") == "TTS ishga tushirish" and category("tts:synth") == "TTS sintez"
    spans = [{"stage": "llm:decide", "ms": 900}, {"stage": "llm:decide", "ms": 1100}, {"stage": "screen:ocr", "ms": 200},
             {"stage": "screen", "ms": 400}, {"stage": "route", "ms": 1}]
    st = aggregate(spans, n_runs=2)
    assert st["LLM (reja/qaror/xulosa)"]["median_ms"] == 1000 and st["LLM (reja/qaror/xulosa)"]["ms_per_task"] == 1000
    assert "screen" not in st
    assert bottlenecks(st, 1)[0]["stage"].startswith("LLM")
    rows = compare({"stages": st}, {"stages": {"OCR": {"median_ms": 100}}})
    ocr = next(r for r in rows if r["stage"] == "OCR")
    assert ocr["change_pct"] == -50.0


# --- TTS nomzodlari ---
def test_tts_candidates_only_installed_and_uz_proxies():
    cfg = Config()
    installed = {"Milena": "ru_RU", "Samantha": "en_US", "Yelda": "tr_TR", "Thomas": "fr_FR"}
    vs = candidates(cfg, installed, all_voices=False, names=[], edge=False)
    names = {v["voice"] for v in vs}
    assert names == {"Milena", "Samantha", "Yelda"}      # fr ovozi kiritilmaydi, o'zbek ovozi "bor" deb yozilmaydi
    phrases = [{"lang": "uz", "category": "uz_special"}, {"lang": "ru", "category": "ru_sentence"},
               {"lang": "en", "category": "mixed"}]
    tr = phrases_for({"engine": "system", "voice": "Yelda", "locale": "tr_TR"}, phrases)
    assert [p["lang"] for p in tr] == ["uz", "en"]        # o'zbekka yaqin ovoz: o'zbek + aralash ibora
    assert candidates(cfg, installed, False, ["Nope", "Milena"], False) == [
        {"engine": "system", "voice": "Milena", "locale": "ru_RU"}]


# --- hisobot ---
def test_report_marks_missing_and_simulated_as_not_tested(tmp_path):
    (tmp_path / "speech-1.json").write_text(json.dumps({"step": "speech", "run_id": "1", "real": False}), encoding="utf-8")
    text = report.build(tmp_path)
    assert text.count("**NOT TESTED**") >= 8
    assert "Windows" in text


def test_report_uses_real_results(tmp_path):
    item = {"id": "v1", "group": "ru", "wer": 0.0, "cer": 0.0, "lid_ok": True, "intent_ok": True, "entity_ok": True,
            "asr_ms": 400, "eos_ms": 1200, "errors": {}, "reference": "a", "hypothesis": "a"}
    data = {"step": "speech", "run_id": "2", "real": True, "engine": "mlx", "model": "large-v3-turbo",
            "model_load_s": 3, "selected_language_prior": "uz", "summary": speech.summarize([item]), "items": [item]}
    (tmp_path / "speech-2.json").write_text(json.dumps(data), encoding="utf-8")
    text = report.build(tmp_path)
    assert "Real mikrofon sinovi: **NOT TESTED**" not in text and "speech-2.json" in text


# --- muhit auditi kalitni chiqarmaydi ---
def test_env_audit_never_contains_secret(tmp_path):
    from xadicha.validation.env_audit import audit

    cfg = Config(provider="mock", anthropic_api_key="sk-ant-SECRET-123456", db_path=tmp_path / "t.db")
    dumped = json.dumps(audit(cfg), default=str)
    assert "SECRET" not in dumped and '"has_anthropic_key": true' in dumped


# --- papka yaratish: nom va joy ---
def test_folder_name_and_location():
    assert folder_path("sinov-12 nomli papka yarat") == "sinov-12"
    assert folder_path('Desktopda "Hisobot" papka yarat') == "~/Desktop/Hisobot"
    assert folder_path('~/XADICHA_TEST ichida "Rasmlar 2026" papkasini yarat') == "~/XADICHA_TEST/Rasmlar 2026"
    assert folder_path("create a folder named Reports") == "Reports"
    assert folder_path("создай папку с именем Отчёт") == "Отчёт"
    assert folder_path("papka yarat") == "Yangi papka"
    assert folder_path('"a/../b" papka yarat') == "a-..-b"   # yo'l ajratgichlari nomga kirmaydi
    assert parse_command("sinov nomli papka yarat", "uz")[1][0].path == "sinov"


def test_relative_folder_goes_into_workspace(cfg, adapter):
    agent = Agent(cfg, ScriptedProvider(), adapter)
    agent.cfg.fast_path = True
    task = agent.run("sinov-7 nomli papka yarat", "uz", Mode.multimodal)
    assert task.steps[0].action.path == str(cfg.workspace / "sinov-7")


# --- o'lchov izlari ---
class _VerifyAdapter(DryRunAdapter):
    def execute(self, action: Action) -> ExecResult:
        return ExecResult(True, "ok", verified=True, verify_ms=37)


def test_verify_and_screen_spans_are_recorded(cfg):
    from xadicha.vision.screen import Screenshot

    shot = Screenshot("", 10, 10, 1.0, timings={"capture": 50, "ocr": 120})
    prov = ScriptedProvider([{"action": {"type": "open_app", "app": "Notes"}}, {"done": True, "final_message": "ok"}])
    prov.supports_vision = True
    agent = Agent(cfg, prov, _VerifyAdapter(), screen_fn=lambda: shot)
    task = agent.run("Notes ni och", "uz", Mode.multimodal)
    stages = [s["stage"] for s in task.trace]
    assert "verify" in stages and "screen:capture" in stages and "screen:ocr" in stages
    assert next(s for s in task.trace if s["stage"] == "verify")["ms"] == 37


def test_plan_mode_records_llm_span(cfg, adapter):
    prov = ScriptedProvider(plan={"steps": [{"action": {"type": "wait", "seconds": 0}}], "final_message": "ok"})
    task = Agent(cfg, prov, adapter).run("kut", "uz", Mode.llm_plan)
    assert any(s["stage"] == "llm:plan" for s in task.trace)


def test_benchmark_gt_method():
    from xadicha.benchmark import gt_method

    assert gt_method({"type": "answer_only"}, DryRunAdapter()) == "human"
    assert gt_method({"type": "frontmost_app"}, DryRunAdapter()) == "action_log"
