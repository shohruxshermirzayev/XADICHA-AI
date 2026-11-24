"""Operatsion tizim adapterlari uchun umumiy interfeys.

Har bir adapter harakatni bajaradi va imkon bo'lsa uni dasturiy tekshiradi
(masalan, papka haqiqatan yaratildimi, kerakli ilova old planga chiqdimi).
Bu vizual tekshiruvni to'ldiruvchi "gibrid tekshiruv"ning birinchi qismi.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..models import Action


@dataclass
class ExecResult:
    ok: bool
    detail: str = ""
    verified: bool | None = None   # dasturiy tekshiruv natijasi; None = dasturiy tekshirib bo'lmaydi


class OSAdapter(ABC):
    name = "base"

    def execute(self, action: Action) -> ExecResult:
        handler = getattr(self, f"_do_{action.type}", None)
        if handler is None:
            return ExecResult(False, f"Qo'llab-quvvatlanmaydigan harakat: {action.type}")
        try:
            return handler(action)
        except Exception as e:  # noqa: BLE001 — adapter xatosi agentni to'xtatmasligi kerak
            return ExecResult(False, f"{e.__class__.__name__}: {e}")

    # --- fayl amallari: barcha tizimlar uchun bir xil ---
    def _do_create_folder(self, a: Action) -> ExecResult:
        p = Path(a.path or "").expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return ExecResult(True, str(p), verified=p.is_dir())

    def _do_create_file(self, a: Action) -> ExecResult:
        p = Path(a.path or "").expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            return ExecResult(False, f"Fayl allaqachon mavjud: {p}", verified=False)
        p.write_text(a.content or "", encoding="utf-8")
        return ExecResult(True, str(p), verified=p.is_file())

    def _do_wait(self, a: Action) -> ExecResult:
        time.sleep(min(max(a.seconds or 1.0, 0.0), 10.0))
        return ExecResult(True)

    def _do_delete_path(self, a: Action) -> ExecResult:
        p = Path(a.path or "").expanduser()
        if not p.exists():
            return ExecResult(False, f"Topilmadi: {p}", verified=False)
        self._to_trash(p)
        return ExecResult(True, f"Savatga o'tkazildi: {p}", verified=not p.exists())

    # --- tizimga xos amallar ---
    @abstractmethod
    def _to_trash(self, path: Path) -> None: ...

    @abstractmethod
    def frontmost_app(self) -> str: ...

    @abstractmethod
    def screen_size(self) -> tuple[int, int]: ...

    def permissions(self) -> dict[str, bool | None]:
        return {}

    # GUI amallari (pyautogui — boshqariladigan zaxira usul)
    def _gui(self):
        import pyautogui

        pyautogui.FAILSAFE = True   # sichqonchani ekran burchagiga olib borish = favqulodda to'xtatish
        pyautogui.PAUSE = 0.15
        return pyautogui

    def _do_click(self, a: Action) -> ExecResult:
        self._gui().click(a.x, a.y)
        return ExecResult(True, f"({a.x}, {a.y})")

    def _do_double_click(self, a: Action) -> ExecResult:
        self._gui().doubleClick(a.x, a.y)
        return ExecResult(True, f"({a.x}, {a.y})")

    def _do_scroll(self, a: Action) -> ExecResult:
        self._gui().scroll(a.amount or -3)
        return ExecResult(True)

    def _do_hotkey(self, a: Action) -> ExecResult:
        keys = [self._map_key(k) for k in (a.keys or [])]
        if not keys:
            return ExecResult(False, "Tugmalar ko'rsatilmagan")
        self._gui().hotkey(*keys)
        return ExecResult(True, "+".join(keys))

    def _do_type_text(self, a: Action) -> ExecResult:
        # pyautogui.write kirill va o'zbek harflarini yoza olmaydi — clipboard orqali joylaymiz
        import pyperclip

        text = a.text or ""
        old = None
        try:
            old = pyperclip.paste()
        except Exception:  # noqa: BLE001
            pass
        pyperclip.copy(text)
        self._gui().hotkey(self._paste_modifier(), "v")
        time.sleep(0.1)
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:  # noqa: BLE001
                pass
        return ExecResult(True, f"{len(text)} belgi")

    def _map_key(self, key: str) -> str:
        return key.strip().lower()

    @abstractmethod
    def _paste_modifier(self) -> str: ...


class DryRunAdapter(OSAdapter):
    """Hech narsani bajarmaydi — testlar va xavfsiz namoyish uchun."""

    name = "dry-run"

    def __init__(self, fail_types: set[str] | None = None):
        self.executed: list[Action] = []
        self.fail_types = fail_types or set()
        self._front = "Finder"

    def execute(self, action: Action) -> ExecResult:
        self.executed.append(action)
        if action.type in self.fail_types:
            return ExecResult(False, "simulyatsiya qilingan xato", verified=False)
        if action.type == "open_app":
            self._front = action.app or ""
            return ExecResult(True, action.app or "", verified=True)
        return ExecResult(True, "dry-run")

    def _to_trash(self, path: Path) -> None:  # pragma: no cover
        pass

    def frontmost_app(self) -> str:
        return self._front

    def screen_size(self) -> tuple[int, int]:
        return (1440, 900)

    def _paste_modifier(self) -> str:  # pragma: no cover
        return "command"
