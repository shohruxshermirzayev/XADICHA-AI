"""Terminal interfeysi.

  python -m xadicha                 # matn bilan buyruq berish
  python -m xadicha --voice         # Enter bosib gapirish
  python -m xadicha --mode B        # eksperiment rejimi (A, B, C)
  python -m xadicha --dry-run       # hech narsani bajarmasdan sinash
  python -m xadicha serve           # API serverni ishga tushirish (interfeys uchun)
"""

from __future__ import annotations

import argparse
import sys

from .config import load_config
from .models import Action, Mode, RiskLevel, TaskRecord
from .service import XadichaService

RISK_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}


def cli_confirm(task: TaskRecord, action: Action, risk: RiskLevel, reason: str) -> bool:
    print(f"\n{RISK_ICON[risk.value]} Tasdiq kerak ({risk.value}): {action.describe()}")
    if reason:
        print(f"   Kutilgan natija: {reason}")
    return input("   Bajarilsinmi? [h/Y — ha, boshqa — yo'q]: ").strip().lower() in {"h", "ha", "y", "yes", "да", "д"}


def print_event(e: dict) -> None:
    t = e["type"]
    if t == "step_finished":
        s = e["step"]
        mark = {"verified": "✅", "executed": "▶️", "failed": "❌", "denied": "⛔", "error": "❌"}.get(s["status"], "•")
        print(f"  {mark} {s['index']}. {s['action']['type']} — {s['status']} {s['detail'][:80]}")
    elif t == "step_verified":
        s = e["step"]
        print(f"     🔎 tekshiruv: {s['index']}-qadam {'tasdiqlandi' if s['verified'] else 'MUVAFFAQIYATSIZ'}")
    elif t == "error":
        print(f"  ⚠️  {e['message']}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="xadicha")
    ap.add_argument("command", nargs="?", default="chat", choices=["chat", "serve"])
    ap.add_argument("--voice", action="store_true", help="mikrofon orqali buyruq")
    ap.add_argument("--mode", default="C", choices=["A", "B", "C"])
    ap.add_argument("--lang", default=None, choices=["uz", "ru", "en"],
                    help="ovozli rejimda tilni majburlash; matnli rejimda javob tili (standart: uz)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if args.command == "serve":
        import uvicorn

        uvicorn.run("xadicha.api:app", host="127.0.0.1", port=args.port)
        return

    cfg = load_config()
    from .adapters import make_adapter

    svc = XadichaService(cfg, adapter=make_adapter(dry_run=args.dry_run))
    svc.agent.confirm = cli_confirm
    svc.subscribe(print_event)
    st = svc.status()
    print(f"XADICHA AI — {st['os']} | model: {st['provider']['name']} "
          f"({'ok' if st['provider']['ok'] else st['provider']['detail']}) | rejim: {args.mode}"
          + (" | DRY-RUN" if args.dry_run else ""))
    print("Chiqish: Ctrl+C. Favqulodda to'xtatish: sichqonchani ekranning yuqori-chap burchagiga olib boring.\n")

    mode = Mode(args.mode)
    while True:
        try:
            if args.voice:
                input("🎙  Gapirish uchun Enter bosing...")
                svc.start_listening(args.lang)
                input("   Tugatganda Enter bosing...")
                print("   ⏳ Matnga aylantirilmoqda...")
                r = svc.stop_listening()
                if not r or not r.text:
                    print("   Hech narsa eshitilmadi.\n")
                    continue
                note = f" (Whisper aniqlagani: {r.detected_raw})" if r.detected_raw and r.detected_raw != r.language else ""
                print(f"   📝 [{r.language}]{note} {r.text}")
                if not r.supported:
                    print("   Bu til qo'llab-quvvatlanmaydi (faqat o'zbek, rus, ingliz).\n")
                    continue
                text, lang = r.text, r.language
            else:
                text = input("Siz: ").strip()
                lang = args.lang or "uz"
            if not text:
                continue
            task = svc.run_task(text, lang, mode)
            print(f"XADICHA [{task.status.value}, {task.latency_ms} ms]: {task.final_message}")
            if args.dry_run:
                print("   ℹ️  DRY-RUN: bu faqat reja — haqiqatda hech narsa bajarilmadi.")
            print()
        except (KeyboardInterrupt, EOFError):
            print("\nXayr!")
            sys.exit(0)


if __name__ == "__main__":
    main()
