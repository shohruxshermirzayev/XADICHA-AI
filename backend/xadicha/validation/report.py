"""8-qadam: yakuniy hisobot — backend/validation/REPORT.md. Faqat saqlangan REAL natijalardan tuziladi.
Natija yo'q yoki real emas bo'lsa — "NOT TESTED". Raqamlar qo'lda kiritilmaydi."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import RESULTS_DIR, VALIDATION_DIR, latest, result_files

NT = "**NOT TESTED**"

STEP_COMMANDS = {
    "env": "python -m xadicha.validate env",
    "speech": "python -m xadicha.validate speech",
    "tts": "python -m xadicha.validate tts",
    "automation": "python -m xadicha.validate automation",
    "search": "python -m xadicha.validate search --judge",
    "profile": "python -m xadicha.validate profile --label before",
    "abc": "python -m xadicha.validate abc",
}

STATIC_LIMITATIONS = [
    "Windows: real Windows kompyuterda sinalmagan — NOT TESTED.",
    "Bitta foydalanuvchi va bitta qurilmada o'lchangan; ovoz, aksent va mikrofon xilma-xilligi qamrab olinmagan.",
    "TTS baholari bitta tinglovchidan (sub'ektiv); MOS uchun bir nechta baholovchi kerak.",
    "Qidiruv natijalari vaqtga bog'liq — qayta ishga tushirilganda boshqacha bo'lishi mumkin.",
    "Ko'rilmagan nutq to'plamini muallif yozgan; u tizimni sozlashda ishlatilmagan, lekin muallif xolisligi istisno emas.",
]


def _real(d: dict[str, Any] | None) -> bool:
    return bool(d and d.get("real"))


def _fmt(v: Any, suffix: str = "") -> str:
    return "—" if v is None else f"{v}{suffix}"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(_fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def sec_env(d: dict[str, Any] | None) -> str:
    if not _real(d) and not (d and d.get("real_device")):
        return NT
    hw, rt, ai, perms, tts = d["hardware"], d["runtimes"], d["ai_provider"], d.get("permissions", {}), d["tts"]
    rows = [
        ["macOS", f"{hw.get('macos_version')} ({hw.get('macos_build')})"], ["Model", hw.get("hardware_model")],
        ["Protsessor", hw.get("cpu")], ["Apple Silicon", hw.get("apple_silicon")], ["RAM", _fmt(hw.get("ram_gb"), " GB")],
        ["Python (Rosetta ostida)", f"{rt.get('python')} ({hw.get('python_under_rosetta')})"], ["Node", rt.get("node")],
        ["ASR dvigateli / model", f"{d.get('stt_engine_resolved')} · {d['config']['whisper_model']}"],
        ["Diskdagi Whisper modellari", ", ".join(m["repo"] for m in d.get("speech_models_on_disk", [])) or "yo'q"],
        ["macOS ovozlari (jami / o'zbek)", f"{tts.get('mac_voice_count')} / {tts.get('mac_uz_voices') or 'yo‘q'}"],
        ["edge-tts o'rnatilgan", tts.get("edge_tts_installed")],
        ["Mikrofon ruxsati", perms.get("microphone")], ["Accessibility", perms.get("accessibility")],
        ["Screen Recording", perms.get("screen_recording")],
        ["AI provayder", f"{ai.get('provider')} · {ai.get('model')} · ishlayapti: {ai.get('health_ok')}"],
        ["Model ekranni ko'radimi", ai.get("supports_vision")],
    ]
    return f"Manba: `env-{d['run_id']}.json`\n\n" + _table(["Ko'rsatkich", "Qiymat"], rows)


def sec_speech(d: dict[str, Any] | None, text: dict[str, Any] | None, rescore: dict[str, Any] | None) -> str:
    parts = []
    if _real(d):
        s = d["summary"]
        parts.append(f"Manba: `speech-{d['run_id']}.json` · {d['engine']} · {d['model']} · model yuklanishi "
                     f"{d.get('model_load_s')} s · prior: {d.get('selected_language_prior')}. Ko'rilmagan to'plam.")
        rows = [[g, b["n_commands"], b["wer_mean"], b["cer_mean"], _fmt(b["lid_accuracy"], "%"),
                 _fmt(b["intent_accuracy"], "%"), _fmt(b["entity_accuracy"], "%"), b["asr_ms_median"], b["eos_ms_median"]]
                for g, b in s["by_group"].items() if g != "silence"]
        o = s["overall"]
        rows.append(["**jami**", o["n_commands"], o["wer_mean"], o["cer_mean"], _fmt(o["lid_accuracy"], "%"),
                     _fmt(o["intent_accuracy"], "%"), _fmt(o["entity_accuracy"], "%"), o["asr_ms_median"], o["eos_ms_median"]])
        parts.append(_table(["Guruh", "n", "WER", "CER", "Til", "Niyat", "Obyekt", "ASR ms (median)", "EOS ms (median)"], rows))
        parts.append(f"Jimlik sinovlari: {o['silence_trials']} ta, shundan yolg'on matn: {o['silence_false_transcriptions']}.")
        if o["error_counts"]:
            parts.append("Xato turlari (necha yozuvda): " + ", ".join(f"{k}={v}" for k, v in sorted(o["error_counts"].items())))
    else:
        parts.append(f"Real mikrofon sinovi: {NT}")
    if rescore and _real(rescore):
        rows = [[k, v["summary"]["overall"]["wer_mean"], v["summary"]["overall"]["cer_mean"],
                 _fmt(v["summary"]["overall"]["lid_accuracy"], "%"), v["summary"]["overall"]["asr_ms_median"], v["model_load_s"]]
                for k, v in rescore["comparisons"].items()]
        parts.append("ASR modellarini solishtirish (o'sha yozuvlarda):\n\n" +
                     _table(["Dvigatel:model", "WER", "CER", "Til", "ASR ms", "Yuklanish s"], rows))
    if text:
        o = text["summary"]["overall"]
        parts.append(f"Qo'shimcha (real nutq EMAS): ko'rilmagan to'plam matni, ASR'siz — til {o['lid_accuracy']}%, "
                     f"niyat {o['intent_accuracy']}%, obyekt {o['entity_accuracy']}% (`speech_text-{text['run_id']}.json`).")
    return "\n\n".join(parts)


def sec_tts(d: dict[str, Any] | None) -> str:
    if not _real(d):
        return NT
    s = d["summary"]
    rows = [[t["engine"], t["voice"], t["locale"], t["mean_score"].get("uz"), t["mean_score"].get("ru"),
             t["mean_score"].get("en"), t["mean_score"].get("cat:uz_special"), t["synth_ms_median"], t["errors"]]
            for t in s["voices"].values()]
    best = ", ".join(f"{lg}: {b['voice']} ({b['mean_score']})" if b else f"{lg}: —" for lg, b in s["best_by_language"].items())
    return (f"Manba: `tts-{d['run_id']}.json` · bitta baholovchi, 1–5 shkala.\n\n"
            + _table(["Dvigatel", "Ovoz", "Locale", "uz", "ru", "en", "o'zbek maxsus harflar", "Sintez ms", "Xato"], rows)
            + f"\n\nEng yaxshi (baho bo'yicha): {best}. O'zbek tizim ovozi: {s['uz_native_system_voice'] or 'yo‘q'}; "
            f"onlayn o'zbek ovozi sozlangan: {s['uz_online_voice_configured']}.")


def sec_search(d: dict[str, Any] | None) -> str:
    if not _real(d):
        return NT
    s = d["summary"]
    rows = [[r["id"], r["lang"], r["type"], r["provider"] or "—", r["n_results"], r["search_ms"],
             (r.get("checks") or {}).get("has_citation"), (r.get("checks") or {}).get("lexical_support"),
             r.get("human_grounded")] for r in d["items"]]
    return (f"Manba: `search-{d['run_id']}.json` · xulosa: {d.get('summarizer')}.\n\n"
            + _table(["So'rov", "Til", "Tur", "Provayder", "Natija", "ms", "Iqtibos", "Leksik tayanch", "Inson: mos"], rows)
            + f"\n\nURL ochilishi: {_fmt(s['url_valid_rate'], '%')}; to'qib chiqarilgan URL bor javoblar: "
            f"{s['answers_with_invented_url']}; noto'g'ri iqtibos: {s['answers_with_invalid_citation']}; inson baholagan "
            f"moslik: {_fmt(s['human_grounded_rate'], '%')}. Ma'nosiz so'rov: {s['nonsense_query']}.")


def sec_automation(d: dict[str, Any] | None) -> str:
    if not _real(d):
        return NT
    rows = [[o["n"], o["operation"], o.get("transcription") or o["requested_command"], o.get("detected_language"),
             o.get("intent"), "; ".join(o.get("planned_actions") or []) or "—",
             "; ".join(f"{a['status']}" for a in o.get("actual_actions") or []) or "—",
             o.get("status"), o.get("duration_ms"), (o.get("error") or "")[:80]] for o in d["operations"]]
    s = d.get("summary") or {}
    return (f"Manba: `automation-{d['run_id']}.json` · test papkasi `{d.get('workspace')}` · ovoz: {d.get('voice')}.\n\n"
            + _table(["#", "Amal", "Buyruq / transkripsiya", "Til", "Niyat", "Reja", "Bajarildi", "Tekshiruv", "ms", "Xato"], rows)
            + f"\n\nNatija: {s}. Agent da'vosi mustaqil tekshiruv bilan mosligi: "
            f"{_fmt(s.get('agent_claim_matches_independent'), '%')}.")


def sec_profile(d: dict[str, Any] | None) -> str:
    if not _real(d):
        return NT
    allst = {**d.get("stages", {}), **{f"{k} (ovoz)": v for k, v in d.get("voice_stages", {}).items()}}
    rows = [[k, v["n"], v["median_ms"], v["p90_ms"], v["max_ms"], v["ms_per_task"]]
            for k, v in sorted(allst.items(), key=lambda kv: -kv[1]["ms_per_task"])]
    top = "; ".join(f"{b['stage']} ({b['ms_per_task']} ms/vazifa)" for b in d.get("bottlenecks_top3", []))
    return (f"Manba: `profile-{d['run_id']}.json` · {d.get('label') or ''} · {d['provider']} {d.get('model') or ''} · "
            f"{d['repeat']} takror (birinchisi sovuq, hisobga olinmagan).\n\n"
            + _table(["Bosqich", "n", "median ms", "p90 ms", "max ms", "ms/vazifa"], rows)
            + f"\n\nEng katta 3 ta tor joy: {top}.\n\nBuyruqlar bo'yicha (median ms): {d.get('per_command_median_ms')}; "
            f"sovuq birinchi ishga tushirish: {d.get('cold_first_run_ms')}.")


def sec_before_after(cmp_: dict[str, Any] | None) -> str:
    if not _real(cmp_):
        return NT + " (optimallashtirish real o'lchovdan keyin qilinadi: `profile --label before`, o'zgarish, `profile --label after`, `profile --compare`)"
    rows = [[r["stage"], r["before_median_ms"], r["after_median_ms"], _fmt(r["change_pct"], "%")] for r in cmp_["rows"]]
    return _table(["Bosqich", "Oldin (median ms)", "Keyin (median ms)", "O'zgarish"], rows)


def sec_abc(d: dict[str, Any] | None) -> str:
    if not _real(d):
        return NT
    rows = [[m, b["n"], _fmt(b["tsr"], "%"), b["latency_ms_median"], b["model_calls_mean"],
             _fmt(b["verification_accuracy"], "%"), _fmt(b["recovery_success_rate"], "%"), _fmt(b["safety_compliance"], "%")]
            for m, b in d["summary"]["by_mode"].items()]
    tsr = {m: b["tsr"] for m, b in d["summary"]["by_mode"].items() if b["tsr"] is not None}
    verdict = ("Natijalar C rejimi eng yuqori muvaffaqiyatga ega ekanini ko'rsatadi." if tsr and max(tsr, key=tsr.get) == "C"
               and list(tsr.values()).count(tsr["C"]) == 1 else
               "Natijalar C rejimining ustunligini ko'rsatmaydi (yoki farq yo'q) — shunday deb yoziladi.")
    return (f"Manba: `abc-{d['run_id']}.json`, xom log `{Path(d['raw_log']).name}` · {d['provider']} {d.get('model') or ''} · "
            f"{d['n_runs']} ishga tushirish · tekshiruv usullari: {d.get('gt_methods')}.\n\n"
            + _table(["Rejim", "n", "TSR", "median ms", "Model chaqiruvi", "Tekshiruv aniqligi", "Tiklanish", "Xavfsizlik"], rows)
            + f"\n\n{verdict} Bitta takror — statistik ahamiyat tekshirilmagan.\n\nCheklovlar:\n"
            + "\n".join(f"- {x}" for x in d.get("limitations", [])))


def failed_tests(res: dict[str, dict[str, Any] | None]) -> list[str]:
    out = []
    sp = res.get("speech")
    if _real(sp):
        for it in sp["items"]:
            if it.get("false_transcription"):
                out.append(f"speech {it['id']}: jimlikda matn chiqdi «{it['hypothesis']}»")
            elif it.get("intent_ok") is False or it.get("lid_ok") is False:
                out.append(f"speech {it['id']}: «{it['reference']}» → «{it['hypothesis']}» (kutilgan {it.get('expected')}, olindi {it.get('got')})")
    au = res.get("automation")
    if _real(au):
        out += [f"automation {o['n']} {o['operation']}: {o['status']} — {o.get('error') or o.get('evidence')}"
                for o in au["operations"] if o.get("status") in ("failed", "unverified")]
    se = res.get("search")
    if _real(se):
        out += [f"search {f['id']}: natija yo'q {f['errors']}" for f in se["summary"]["failures"]]
        out += [f"search {r['id']}: inson baholashi — mos emas" for r in se["items"] if r.get("human_grounded") is False]
    tt = res.get("tts")
    if _real(tt):
        out += [f"tts {i['voice']} {i['phrase_id']}: sintez xatosi {i['error']}" for i in tt["items"] if i.get("error")]
    return out


def manual_steps(res: dict[str, dict[str, Any] | None]) -> list[str]:
    steps = []
    env = res.get("env")
    env = env if env and env.get("real_device") else None
    if env:
        for k, how in (env.get("permissions") or {}).get("how_to_fix", {}).items():
            steps.append(f"Ruxsat bering ({k}): {how}")
        if env.get("hardware", {}).get("python_under_rosetta"):
            steps.append("arm64 Python bilan venv yarating (Rosetta ostida MLX ishlamaydi).")
        if not env.get("speech_models_on_disk"):
            steps.append("Whisper modeli hali yuklanmagan — birinchi `speech` qadamida avtomatik yuklanadi (internet kerak).")
        if not env["tts"].get("edge_tts_installed"):
            steps.append("O'zbekcha onlayn ovozni sinash uchun: `pip install edge-tts` (ixtiyoriy, internet kerak).")
        if not env["ai_provider"].get("health_ok"):
            steps.append("AI model ishlamayapti: `ollama serve` va `ollama pull " + str(env["ai_provider"].get("model")) + "`.")
    for step, cmd in STEP_COMMANDS.items():
        if not _real(res.get(step)) and not (step == "env" and env):
            steps.append(f"`{cmd}` ni ishga tushiring ({step}: hali {NT}).")
    if not _real(res.get("profile_compare")):
        steps.append("Optimallashtirishdan keyin: `python -m xadicha.validate profile --label after` va `--compare`.")
    steps.append("Windows: real Windows kompyuterda sinov (hozircha imkoni yo'q) — NOT TESTED.")
    return steps


def build(results_dir: Path | None = None) -> str:
    rd = results_dir or RESULTS_DIR
    names = ("env", "speech", "speech_text", "speech_rescore", "tts", "search", "automation", "profile",
             "profile_compare", "abc")
    res = {n: latest(n, rd) for n in names}
    total_files = sum(len(result_files(n, rd)) for n in names)
    lines = [
        "# XADICHA AI — real MacBook validatsiyasi hisoboti",
        "",
        f"Yaratildi: {time.strftime('%Y-%m-%d %H:%M')} · natija fayllari: {total_files} ta · papka: `backend/validation/results/`.",
        "Hisobot faqat saqlangan real o'lchovlardan avtomatik tuzilgan. Simulyatsiya yoki o'tkazilmagan sinov — "
        f"{NT}. Avtomatik testlar (pytest, e2e) bu yerda real natija sifatida hisoblanmaydi.",
        "",
        "## 1. Mac muhiti", sec_env(res["env"]),
        "## 2. Real nutq sinovi", sec_speech(res["speech"], res["speech_text"], res["speech_rescore"]),
        "## 3. Real TTS", sec_tts(res["tts"]),
        "## 4. Real internet qidiruvi", sec_search(res["search"]),
        "## 5. Real macOS avtomatlashtirish", sec_automation(res["automation"]),
        "## 6. Kechikish taqsimoti", sec_profile(res["profile"]),
        "## 7. Oldin / keyin", sec_before_after(res["profile_compare"]),
        "## 8. A/B/C taqqoslash", sec_abc(res["abc"]),
        "## 9. Yiqilgan sinovlar",
        "\n".join(f"- {x}" for x in failed_tests(res)) or "Real natijalarda yiqilgan sinov yo'q (yoki sinovlar o'tkazilmagan).",
        "## 10. Qolgan cheklovlar", "\n".join(f"- {x}" for x in STATIC_LIMITATIONS),
        "## 11. Siz bajarishingiz kerak bo'lgan qadamlar", "\n".join(f"{i}. {x}" for i, x in enumerate(manual_steps(res), 1)),
        "",
    ]
    return "\n\n".join(x for x in lines if x) + "\n"


def main(args) -> int:
    text = build()
    path = VALIDATION_DIR / "REPORT.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSaqlandi: {path}")
    return 0
