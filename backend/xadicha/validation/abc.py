"""7-qadam: A/B/C tajribasi — bir xil real vazifalar, bir xil sharoit (benchmark.py real rejimi ustida).

  python -m xadicha.validate abc                      # 12 ta xavfsiz "core" vazifa × uz,ru,en × A,B,C
  python -m xadicha.validate abc --tasks all          # barcha 32 vazifa
  python -m xadicha.validate abc --modes C --langs uz --tasks open_calculator,url_kunuz

A — faqat ovoz/matn: qoida asosida bitta harakat, ekransiz.
B — LLM reja: ekransiz, bir martalik reja.
C — multimodal: ekran + har qadamdan keyin tekshiruv + tiklanish.
O'lchanadi: muvaffaqiyat (mustaqil tekshiruv), vaqt, model chaqiruvlari, tekshiruv aniqligi, tiklanish.
C yaxshiroq deb faqat natijalar shuni ko'rsatsa aytiladi — hisobot raqamlarni o'zi chiqaradi.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import ask, is_macos, save_result

CORE_TASKS = ("open_calculator", "open_notes", "open_finder", "url_kunuz", "url_wikipedia", "search_weather",
              "folder_report", "folder_thesis", "multi_safari_kunuz", "multi_textedit_type", "safety_delete",
              "safety_terminal")

LIMITATIONS = [
    "Bitta qurilma, bitta foydalanuvchi, bitta model — natijalarni umumlashtirib bo'lmaydi.",
    "Vazifalar to'plamini muallif tuzgan (tanlov xolisligi xavfi).",
    "Har vazifa bir marta bajariladi (takrorlar yo'q) — kichik farqlar statistik ahamiyatli emas.",
    "Ba'zi tekshiruvlar faqat bajarilgan harakat logi orqali (gt_method=action_log) — mustaqil emas.",
    "Ekran holati vazifalar orasida to'liq tiklanmaydi (ochiq oynalar keyingi vazifaga ta'sir qilishi mumkin).",
    "A rejimi modelsiz; B va C bir xil modeldan foydalanadi — farq faqat ekran/tekshiruv/tiklanishda.",
]


def main(args) -> int:
    from ..adapters import make_adapter
    from ..adapters.base import DryRunAdapter
    from ..benchmark import bench_dir, load_tasks, run
    from ..config import load_config
    from ..metrics import summarize_runs
    from ..providers import make_provider

    if not is_macos():
        print("A/B/C tajribasi faqat Mac'da (real adapter bilan) o'tkaziladi.")
        return 2
    cfg = load_config()
    if args.tasks == "core":
        ids = set(CORE_TASKS)
    elif args.tasks == "all":
        ids = None
    else:
        ids = {t.strip() for t in args.tasks.split(",") if t.strip()}
    known = {t["id"] for t in load_tasks()}
    if ids and not ids <= known:
        print(f"Noma'lum vazifa: {sorted(ids - known)}")
        return 2
    modes, langs = args.modes.split(","), args.langs.split(",")
    n = len(ids or known) * len(modes) * len(langs)
    bench = bench_dir(cfg)
    print(f"A/B/C tajribasi: {n} ta ishga tushirish. Papka/fayllar faqat {bench} ichida yaratiladi.\n"
          "Ilovalar ochiladi va TextEdit'ga matn yoziladi (saqlanmaydi). Xavfli amallar avtomatik rad etiladi.\n"
          "Sinov paytida klaviatura va sichqonchaga tegmang. To'xtatish: Ctrl+C.")
    if not ask("Boshlaymizmi?"):
        return 1
    adapter = make_adapter()
    if isinstance(adapter, DryRunAdapter):
        print("Real adapter yo'q.")
        return 2
    provider = make_provider(cfg)
    from .. import service as _svc  # ekran + OCR/AX konteksti ilovadagidek

    svc = _svc.XadichaService(cfg, provider=provider, adapter=adapter)
    bench.mkdir(parents=True, exist_ok=True)
    out = Path(__file__).resolve().parent.parent.parent / "benchmark" / "results" / f"run-{time.strftime('%Y%m%d-%H%M%S')}-REAL.jsonl"
    try:
        rows = run(cfg, provider, adapter, modes, langs, ids, out, False, screen_fn=svc._capture_with_context)
    except KeyboardInterrupt:
        from ..benchmark import read_rows

        print("\nTo'xtatildi — shu paytgacha yozilganlar hisoblanadi.")
        rows = read_rows([out]) if out.exists() else []
    summary = summarize_runs(rows)
    methods = {}
    for r in rows:
        methods[r.get("gt_method", "?")] = methods.get(r.get("gt_method", "?"), 0) + 1
    path = save_result("abc", {"real": True, "raw_log": str(out), "provider": provider.name,
                               "model": getattr(provider, "model", None), "modes": modes, "langs": langs,
                               "tasks": sorted(ids or known), "n_runs": len(rows), "gt_methods": methods,
                               "summary": summary, "limitations": LIMITATIONS})
    print("\nRejimlar bo'yicha:")
    for m, b in summary["by_mode"].items():
        print(f"  {m}: TSR={b['tsr']}%  median={b['latency_ms_median']} ms  model chaqiruvi={b['model_calls_mean']}  "
              f"tekshiruv aniqligi={b['verification_accuracy']}%  tiklanish={b['recovery_success_rate']}%")
    print(f"Xom log: {out}\nSaqlandi: {path}")
    return 0
