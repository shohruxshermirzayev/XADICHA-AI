"""4-qadam: real macOS avtomatlashtirish — 11 ta amal + har birini agentdan MUSTAQIL tekshirish (12-band).

  python -m xadicha.validate automation               # matnli buyruqlar
  python -m xadicha.validate automation --voice       # buyruqni mikrofonga aytasiz (to'liq zanjir)
  python -m xadicha.validate automation --only 1,5,7

Xavfsizlik: faqat alohida test papkasi (standart ~/XADICHA_TEST); haqiqiy hujjatlarga tegilmaydi, hech narsa
o'chirilmaydi; to'lov, parol va hisob sozlamalari bilan ishlanmaydi. Tasdiq so'ralsa — terminalda SIZ javob berasiz.
Notes'da bitta sinov eslatmasi yaratiladi (o'chirilmaydi — keyin o'zingiz o'chirasiz).
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any

from . import RESULTS_DIR, ask, is_macos, save_result, stamp
from . import macprobe


def operations(ws: Path, sample: Path, folder: str, marker: str) -> list[dict[str, Any]]:
    return [
        {"n": 1, "name": "open_safari", "command": "Safari ni och", "lang": "uz", "check": ("frontmost", "Safari")},
        {"n": 2, "name": "open_calculator", "command": "Kalkulyatorni och", "lang": "uz", "check": ("frontmost", "Calculator")},
        {"n": 3, "name": "open_finder", "command": "Finder ni och", "lang": "uz", "check": ("frontmost", "Finder")},
        {"n": 4, "name": "open_notes", "command": "Notes ni och", "lang": "uz", "check": ("frontmost", "Notes")},
        {"n": 5, "name": "open_website", "command": "kun.uz saytini och", "lang": "uz", "check": ("url", "kun.uz")},
        {"n": 6, "name": "browser_search", "command": "Google dan Toshkent ob-havosi qidir", "lang": "uz",
         "check": ("url", "google.")},
        {"n": 7, "name": "create_folder", "command": f"{folder} nomli papka yarat", "lang": "uz",
         "check": ("dir", str(ws / folder))},
        {"n": 8, "name": "find_file", "command": f"{sample.stem} faylini top", "lang": "uz",
         "check": ("result", str(sample))},
        {"n": 9, "name": "reveal_file", "command": "shu faylni ko'rsat", "lang": "uz",
         "check": ("finder_selection", str(sample))},
        {"n": 10, "name": "describe_screen", "command": "Ekranda nima turganini aytib ber", "lang": "uz",
         "check": ("human", "Tavsif ekrandagi narsaga mosmi?"), "needs_llm": True},
        {"n": 11, "name": "notes_interaction",
         "command": f'Notes ni och va yangi eslatma yaratib unga "{marker}" deb yoz', "lang": "uz",
         "check": ("notes", marker), "needs_llm": True},
    ]


def verify(check: tuple[str, str], task) -> tuple[bool | None, str]:
    """Mustaqil tekshiruv: (natija, dalil). None — avtomatik tekshirib bo'lmadi (sababi dalilda)."""
    kind, want = check
    if kind == "frontmost":
        time.sleep(0.5)
        front = macprobe.frontmost_app()
        return (None, "old plandagi ilovani o'qib bo'lmadi") if front is None else (want.lower() in front.lower(), f"old planda: {front}")
    if kind == "url":
        time.sleep(2.0)   # sahifa ochilishi uchun
        url = macprobe.browser_url()
        if url is None:
            return None, "brauzer manzilini o'qib bo'lmadi (Automation ruxsati yoki brauzer qo'llab-quvvatlanmaydi)"
        return want in url.lower(), f"manzil: {url[:160]}"
    if kind == "dir":
        p = Path(want).expanduser()
        return p.is_dir(), f"{p} {'bor' if p.is_dir() else 'yo‘q'}"
    if kind == "result":
        paths = [r.get("path") for r in (task.data.get("results") or [])]
        return want in paths, f"natijalar: {paths[:5]}"
    if kind == "finder_selection":
        time.sleep(1.0)
        sel = macprobe.finder_selection()
        if sel is None:
            return None, "Finder tanlovini o'qib bo'lmadi (Automation ruxsati)"
        return Path(sel).resolve() == Path(want).resolve(), f"tanlangan: {sel}"
    if kind == "notes":
        time.sleep(1.0)
        title = macprobe.notes_first_title()
        if title is None:
            return None, "Notes'ni o'qib bo'lmadi (Automation ruxsati)"
        return want.lower() in title.lower(), f"birinchi eslatma: {title[:80]}"
    if kind == "human":
        print(f"     Javob: «{task.final_message}»")
        return ask(want), "inson baholadi"
    return None, "noma'lum tekshiruv"


def console_confirm(task, action, risk, reason) -> bool:
    print(f"\n   ⚠ Tasdiq so'raldi: {action.describe()}  (xavf: {risk.value})")
    return ask("   Ruxsat berasizmi?")


def record_task(task) -> dict[str, Any]:
    return {
        "intent": task.intent, "planner": task.planner, "status": task.status.value,
        "final_message": task.final_message, "llm_calls": task.llm_calls,
        "planned_actions": [s.action.describe() for s in task.steps],
        "actual_actions": [{"action": s.action.describe(), "status": s.status.value, "detail": s.detail,
                            "agent_verified": s.verified, "ms": s.duration_ms} for s in task.steps],
        "trace": task.trace, "timings": task.timings, "resolved_from": task.resolved_from,
    }


def main(args) -> int:
    from ..config import load_config
    from ..models import Mode, TaskStatus
    from ..service import XadichaService

    if not is_macos():
        print("Bu sinov faqat Mac'da (real qurilmada) o'tkaziladi.")
        return 2
    run_id = stamp()
    ws = Path(args.workspace).expanduser()
    cfg0 = load_config()
    print("XADICHA AI — real macOS amallari sinovi\n"
          f"  Test papkasi: {ws}  (faqat shu yerda papka/fayl yaratiladi, hech narsa o'chirilmaydi)\n"
          "  Ochiladi: Safari, Calculator, Finder, Notes, kun.uz, Google qidiruvi.\n"
          "  Notes'da bitta sinov eslatmasi yaratiladi — keyin o'zingiz o'chirasiz.\n"
          "  macOS 'Automation' ruxsatini so'rasa (Safari, Finder, Notes, System Events) — tekshiruv uchun 'OK' bosing.\n"
          "  Sinov paytida klaviatura va sichqonchaga tegmang.")
    if not ask("Boshlaymizmi?"):
        return 1
    ws.mkdir(parents=True, exist_ok=True)
    sample = ws / f"xadicha_namuna_{run_id.replace('-', '_')}.txt"
    sample.write_text("XADICHA AI sinov fayli. O'chirsangiz bo'ladi.\n", encoding="utf-8")
    folder = f"sinov-{run_id}"
    marker = f"XADICHA sinov {run_id}"
    cfg = dataclasses.replace(cfg0, workspace=ws, db_path=RESULTS_DIR / f"automation-{run_id}" / "tasks.db")
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    svc = XadichaService(cfg)
    svc.agent.confirm = console_confirm
    has_llm = svc.provider.name != "rules"
    if args.voice:
        print("Nutq modeli yuklanmoqda...")
        svc.listener.warmup()
    time.sleep(2.0)   # Spotlight yangi faylni indekslashi uchun
    only = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
    results = []
    for op in operations(ws, sample, folder, marker):
        if only and op["n"] not in only:
            continue
        rec: dict[str, Any] = {"n": op["n"], "operation": op["name"], "requested_command": op["command"]}
        if op.get("needs_llm") and not has_llm:
            rec.update(status="NOT TESTED", error=f"AI provayder yo'q ({svc.provider_error or 'rules'})")
            results.append(rec)
            print(f"[{op['n']:2}] {op['name']}: NOT TESTED — model yo'q")
            continue
        print(f"\n[{op['n']:2}] {op['name']}: «{op['command']}»")
        instruction, lang = op["command"], op["lang"]
        if args.voice:
            import threading

            from ..lang import refine_asr_language
            from ..speech.stt import Endpointer

            input("     Enter bosing va buyruqni ayting...")
            ep, stop = Endpointer(), threading.Event()
            audio = svc.listener.record_until(stop, max_seconds=15, endpointer=ep)
            t_asr = time.perf_counter()
            tr = svc.listener.transcribe(audio, None, prior="uz")
            lang = refine_asr_language(tr.text, tr.language, tr.probability or None, "uz") if tr.text else tr.language
            rec.update(transcription=tr.text, asr_ms=round((time.perf_counter() - t_asr) * 1000),
                       eos_ms=round(ep.endpoint_delay_s * 1000))
            print(f"     eshitildi: «{tr.text}» ({lang})")
            instruction = tr.text or instruction
        rec.update(detected_language=lang)
        t0 = time.perf_counter()
        try:
            task = svc.run_task(instruction, lang, Mode.multimodal, speak=False)
        except Exception as e:  # noqa: BLE001
            rec.update(status="failed", error=f"{e.__class__.__name__}: {e}", duration_ms=round((time.perf_counter() - t0) * 1000))
            results.append(rec)
            continue
        rec["duration_ms"] = round((time.perf_counter() - t0) * 1000)
        rec.update(record_task(task))
        ok, evidence = verify(op["check"], task)
        rec.update(independent_verification=ok, evidence=evidence,
                   agent_claimed_success=task.status == TaskStatus.success)
        rec["status"] = "passed" if ok else ("failed" if ok is False else "unverified")
        if rec["status"] != "passed":
            rec["error"] = task.final_message if task.status != TaskStatus.success else evidence
        mark = {"passed": "✅", "failed": "❌", "unverified": "❔"}[rec["status"]]
        print(f"     {mark} {rec['status']} · {rec['duration_ms']} ms · {evidence}")
        results.append(rec)
        save_result("automation", {"real": True, "workspace": str(ws), "operations": results}, run_id)
        time.sleep(0.8)
    tested = [r for r in results if r["status"] != "NOT TESTED"]
    agree = [r for r in tested if r.get("independent_verification") is not None]
    summary = {
        "n": len(results), "passed": sum(r["status"] == "passed" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
        "unverified": sum(r["status"] == "unverified" for r in results),
        "not_tested": sum(r["status"] == "NOT TESTED" for r in results),
        # 12-band: agent o'zini muvaffaqiyatli deb hisoblagani mustaqil tekshiruv bilan qanchalik mos
        "agent_claim_matches_independent": (round(100 * sum(r["agent_claimed_success"] == r["independent_verification"]
                                                            for r in agree) / len(agree), 1) if agree else None),
    }
    path = save_result("automation", {"real": True, "workspace": str(ws), "voice": args.voice, "provider": svc.provider.name,
                                      "summary": summary, "operations": results}, run_id)
    print(f"\nNatija: {summary}\nSaqlandi: {path}\nTest papkasi: {ws} (o'zingiz o'chirasiz). Notes'dagi «{marker}» eslatmasini o'chiring.")
    return 0
