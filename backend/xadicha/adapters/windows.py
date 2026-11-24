"""Windows adapteri: `start`, os.startfile, UI Automation (pywinauto, ixtiyoriy); pyautogui — zaxira.

DIQQAT: Windows qurilmasida hali sinab ko'rilmagan.
"""

from __future__ import annotations

import subprocess
import time
import webbrowser
from pathlib import Path

from ..models import Action
from .base import ExecResult, OSAdapter

_KEYMAP = {"command": "ctrl", "cmd": "ctrl", "option": "alt", "return": "enter", "esc": "escape"}

_APP_ALIASES = {
    "notepad": "notepad", "bloknot": "notepad", "блокнот": "notepad",
    "calculator": "calc", "kalkulyator": "calc", "калькулятор": "calc",
    "explorer": "explorer", "file explorer": "explorer", "provodnik": "explorer", "проводник": "explorer",
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge",
    "word": "winword", "excel": "excel", "paint": "mspaint", "settings": "ms-settings:",
}


class WindowsAdapter(OSAdapter):
    name = "windows"

    def _do_open_app(self, a: Action) -> ExecResult:
        name = (a.app or "").strip()
        target = _APP_ALIASES.get(name.lower(), name)
        r = subprocess.run(["cmd", "/c", "start", "", target], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return ExecResult(False, f"'{name}' ishga tushmadi", verified=False)
        time.sleep(1.5)
        front = self.frontmost_app()
        ok = bool(front) and name.lower().split()[0] in front.lower()
        return ExecResult(True, front, verified=True if ok else None)

    def _do_open_url(self, a: Action) -> ExecResult:
        ok = webbrowser.open(a.url or "")
        return ExecResult(ok, a.url or "", verified=None if ok else False)

    def _to_trash(self, path: Path) -> None:
        try:
            from send2trash import send2trash
        except ImportError as e:
            raise RuntimeError("Savatga o'tkazish uchun: pip install send2trash") from e
        send2trash(str(path))

    def frontmost_app(self) -> str:
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:  # noqa: BLE001
            return ""

    def screen_size(self) -> tuple[int, int]:
        import pyautogui

        w, h = pyautogui.size()
        return int(w), int(h)

    def _map_key(self, key: str) -> str:
        k = key.strip().lower()
        return _KEYMAP.get(k, k)

    def _paste_modifier(self) -> str:
        return "ctrl"

