"""macOS adapteri: `open`, AppleScript (osascript) va Accessibility; pyautogui — zaxira."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from ..models import Action
from .base import ExecResult, OSAdapter

_KEYMAP = {"cmd": "command", "ctrl": "ctrl", "control": "ctrl", "opt": "option", "alt": "option",
           "return": "enter", "esc": "escape"}


def osascript(script: str, timeout: float = 10) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "osascript xatosi")
    return r.stdout.strip()


class MacOSAdapter(OSAdapter):
    name = "macos"

    def _do_open_app(self, a: Action) -> ExecResult:
        app = (a.app or "").strip()
        r = subprocess.run(["open", "-a", app], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return ExecResult(False, f"'{app}' ilovasi topilmadi", verified=False)
        # Dasturiy tekshiruv: ilova old planga chiqdimi
        for _ in range(20):
            time.sleep(0.25)
            front = self.frontmost_app()
            if front and (app.lower() in front.lower() or front.lower() in app.lower()):
                return ExecResult(True, front, verified=True)
        return ExecResult(True, f"ochildi, lekin old planda: {self.frontmost_app()}", verified=None)

    def _do_open_url(self, a: Action) -> ExecResult:
        url = a.url or ""
        if not url.lower().startswith(("http://", "https://", "mailto:", "tel:")):
            # Xavfsizlik qatlami buni allaqachon taqiqlaydi; bu — ikkinchi himoya (`open <yo'l>` ilovani ishga tushiradi)
            return ExecResult(False, "Faqat http/https manzillar ochiladi", verified=False)
        r = subprocess.run(["open", url], capture_output=True, text=True, timeout=15)
        return ExecResult(r.returncode == 0, a.url or "", verified=None if r.returncode == 0 else False)

    def _to_trash(self, path: Path) -> None:
        # Finder orqali Savatga — qaytarib olsa bo'ladi
        posix = str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
        osascript(f'tell application "Finder" to delete (POSIX file "{posix}" as alias)')

    def frontmost_app(self) -> str:
        try:
            return osascript('tell application "System Events" to get name of first application process '
                             'whose frontmost is true', timeout=5)
        except Exception:  # noqa: BLE001
            return ""

    def screen_size(self) -> tuple[int, int]:
        import pyautogui

        w, h = pyautogui.size()
        return int(w), int(h)

    def permissions(self) -> dict[str, bool | None]:
        acc: bool | None
        try:
            osascript('tell application "System Events" to get name of first process', timeout=5)
            acc = True
        except Exception:  # noqa: BLE001
            acc = False
        return {"accessibility": acc, "screen_recording": None, "microphone": None}

    def _map_key(self, key: str) -> str:
        k = key.strip().lower()
        return _KEYMAP.get(k, k)

    def _paste_modifier(self) -> str:
        return "command"
