"""Real qurilmada validatsiya (macOS): muhit, nutq, TTS, avtomatlashtirish, qidiruv, tezlik, A/B/C, hisobot.

Ishga tushirish:  cd backend && source .venv/bin/activate && python -m xadicha.validate <qadam>
Har bir qadam natijasi: backend/validation/results/<qadam>-<vaqt>.json (+ audio papkalari).
Qoidalar: natijalar faqat haqiqiy o'lchovdan yoziladi; simulyatsiya yoki o'tkazib yuborilgan narsa
"NOT TESTED" deb belgilanadi. Kalitlar va maxfiy qiymatlar hech qachon yozilmaydi.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
VALIDATION_DIR = BACKEND_DIR / "validation"
RESULTS_DIR = VALIDATION_DIR / "results"

STEPS = ("env", "speech", "tts", "automation", "search", "profile", "abc")


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def is_macos() -> bool:
    return platform.system() == "Darwin"


def save_result(step: str, data: dict[str, Any], run_id: str | None = None) -> Path:
    """Natijani JSON sifatida saqlaydi. Har bir faylda qadam, vaqt va "real" belgisi bo'ladi."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = run_id or stamp()
    path = RESULTS_DIR / f"{step}-{run_id}.json"
    payload = {"step": step, "run_id": run_id, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "platform": platform.platform(), **data}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def result_files(step: str, results_dir: Path | None = None) -> list[Path]:
    d = results_dir or RESULTS_DIR
    return sorted(d.glob(f"{step}-*.json")) if d.exists() else []


def latest(step: str, results_dir: Path | None = None) -> dict[str, Any] | None:
    files = result_files(step, results_dir)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def ask(question: str, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    ans = input(f"▶ {question}{suffix}").strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes", "h", "ha"}


def ask_score(question: str) -> int | None:
    """1..5 baho; bo'sh yoki "s" — o'tkazib yuborish (None)."""
    while True:
        ans = input(f"▶ {question} [1-5, s=o'tkazish]: ").strip().lower()
        if ans in {"", "s"}:
            return None
        if ans.isdigit() and 1 <= int(ans) <= 5:
            return int(ans)
        print("   1 dan 5 gacha son kiriting.")
