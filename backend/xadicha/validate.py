"""Real Mac validatsiyasi — yagona kirish nuqtasi.

  python -m xadicha.validate env          # 1. muhit auditi (ruxsat so'ramaydi)
  python -m xadicha.validate speech       # 2. mikrofon + ASR, ko'rilmagan to'plam (siz o'qiysiz)
  python -m xadicha.validate tts          # 3. ovozlar (siz tinglab baholaysiz)
  python -m xadicha.validate automation   # 4. macOS amallari, alohida test papkasida (har biridan oldin so'raydi)
  python -m xadicha.validate search       # 5. real internet qidiruvi
  python -m xadicha.validate profile      # 6. bosqichlar vaqti (bir xil buyruqlar, takroriy)
  python -m xadicha.validate abc          # 7. A/B/C tajribasi (benchmark, real rejim)
  python -m xadicha.validate report       # 8. yakuniy hisobot: backend/validation/REPORT.md
Batafsil: docs/REAL_VALIDATION.md
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="xadicha.validate")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("env")

    sp = sub.add_parser("speech")
    sp.add_argument("--only", default="", help="guruhlar: uz_latn,uz_cyrl,ru,en,mixed,silence")
    sp.add_argument("--limit", type=int, default=0)
    sp.add_argument("--selected", default="uz", help="interfeysda tanlangan til (ASR uchun prior)")
    sp.add_argument("--rescore", default="", help="saqlangan yozuvlar papkasi — qayta baholash")
    sp.add_argument("--models", default="")
    sp.add_argument("--engines", default="")
    sp.add_argument("--text-only", action="store_true", help="ASR'siz, faqat matn (real nutq natijasi emas)")
    sp.add_argument("--set", default="heldout", choices=["heldout", "dev", "regression"],
                    help="heldout — ko'rilmagan (sozlashda ishlatilmaydi), dev — sozlash, regression — eski to'plam")
    sp.add_argument("--providers", default="whisper", help="qayta baholash: whisper,gemini,gemini-live")
    sp.add_argument("--speaker", default="", help="taxallus (ism emas), masalan: s01")
    sp.add_argument("--env", default="quiet", choices=["quiet", "noisy"], help="yozuv muhiti")
    sp.add_argument("--speed", default="normal", choices=["slow", "normal", "fast"], help="nutq tezligi")

    tp = sub.add_parser("tts")
    tp.add_argument("--all-voices", action="store_true", help="o'rnatilgan BARCHA ovozlar (uzoq)")
    tp.add_argument("--voices", default="", help="vergul bilan aniq ovoz nomlari")
    tp.add_argument("--no-rate", action="store_true", help="baholamasdan faqat sintez va vaqt")

    ap_auto = sub.add_parser("automation")
    ap_auto.add_argument("--only", default="", help="amal raqamlari: 1,2,5")
    ap_auto.add_argument("--voice", action="store_true", help="buyruqni mikrofonga aytish (aks holda matn)")
    ap_auto.add_argument("--workspace", default="~/XADICHA_TEST")

    se = sub.add_parser("search")
    se.add_argument("--judge", action="store_true", help="har javobni o'zingiz baholaysiz (manbaga mosmi)")
    se.add_argument("--no-summary", action="store_true", help="modelsiz, faqat qidiruv natijalari")

    pr = sub.add_parser("profile")
    pr.add_argument("--repeat", type=int, default=3)
    pr.add_argument("--label", default="", help="masalan: before / after")
    pr.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"), help="ikki profil faylini solishtirish")

    ab = sub.add_parser("abc")
    ab.add_argument("--modes", default="A,B,C")
    ab.add_argument("--langs", default="uz,ru,en")
    ab.add_argument("--tasks", default="core", help="'core' (12 ta xavfsiz vazifa), 'all' yoki id lar")

    sub.add_parser("report")
    args = ap.parse_args(argv)

    if args.step == "env":
        from .validation.env_audit import main as run
    elif args.step == "speech":
        from .validation.speech import main as run
    elif args.step == "tts":
        from .validation.tts_eval import main as run
    elif args.step == "automation":
        from .validation.automation import main as run
    elif args.step == "search":
        from .validation.search_eval import main as run
    elif args.step == "profile":
        from .validation.profile import main as run
    elif args.step == "abc":
        from .validation.abc import main as run
    else:
        from .validation.report import main as run
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
