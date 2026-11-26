"""Windows adapteri: `start`, os.startfile, UI Automation (pywinauto, ixtiyoriy); pyautogui — zaxira.

DIQQAT: Windows qurilmasida hali sinab ko'rilmagan.
"""

from __future__ import annotations

import subprocess
import time
import webbrowser
from pathlib import Path

from ..redaction import safe_env
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
        if not name or any(c in name for c in '&|<>^%"`\n\r'):
            # `cmd /c start` qobiq orqali ishlaydi — maxsus belgilar buyruq in'eksiyasiga olib keladi
            return ExecResult(False, "Ilova nomida ruxsat etilmagan belgilar bor", verified=False)
        target = _APP_ALIASES.get(name.lower(), name)
        r = subprocess.run(["cmd", "/c", "start", "", target], env=safe_env(), capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return ExecResult(False, f"'{name}' ishga tushmadi", verified=False)
        time.sleep(1.5)
        front = self.frontmost_app()
        ok = bool(front) and name.lower().split()[0] in front.lower()
        return ExecResult(True, front, verified=True if ok else None)

    def _do_open_url(self, a: Action) -> ExecResult:
        url = a.url or ""
        if not url.lower().startswith(("http://", "https://", "mailto:", "tel:")):
            return ExecResult(False, "Faqat http/https manzillar ochiladi", verified=False)
        ok = webbrowser.open(url)
        return ExecResult(ok, a.url or "", verified=None if ok else False)

    def _do_system(self, a: Action) -> ExecResult:
        """DIQQAT: Windows'da sinalmagan. Ovoz — multimedia tugmalari (har bosish ~2%), yorqinlik — WMI."""
        c = a.control
        step = int(a.amount) if a.amount is not None else 10
        gui = self._gui()
        if c == "volume_up":
            gui.press("volumeup", presses=max(1, step // 2))
            return ExecResult(True, f"ovoz +{step}%", verified=None)
        if c == "volume_down":
            gui.press("volumedown", presses=max(1, step // 2))
            return ExecResult(True, f"ovoz -{step}%", verified=None)
        if c == "volume_set":
            gui.press("volumedown", presses=50)
            gui.press("volumeup", presses=max(0, min(100, step)) // 2)
            return ExecResult(True, f"ovoz ≈{step}%", verified=None)
        if c in ("mute", "unmute"):
            gui.press("volumemute")   # Windows'da holatni o'qib bo'lmaydi — almashtirish tugmasi
            return ExecResult(True, "ovoz o'chirish/yoqish tugmasi bosildi", verified=None)
        if c in ("brightness_up", "brightness_down"):
            delta = step if c == "brightness_up" else -step
            ps = ("$b=(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness;"
                  f"$n=[Math]::Max(0,[Math]::Min(100,$b+({int(delta)})));"
                  "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
                  ".WmiSetBrightness(1,$n) | Out-Null; $n")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=safe_env(), capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                return ExecResult(False, "Yorqinlikni o'zgartirib bo'lmadi (tashqi monitor?)", verified=False)
            return ExecResult(True, f"yorqinlik {r.stdout.strip()}%", verified=None)
        if c == "battery":
            return self._battery()
        return ExecResult(False, f"Noma'lum tizim boshqaruvi: {c}", verified=False)

    def _battery(self) -> ExecResult:
        """Batareya zaryadi — psutil.sensors_battery() (faqat o'qish). Batareya yo'q bo'lsa — "topilmadi"."""
        try:
            import psutil
        except ImportError:
            return ExecResult(False, "psutil o'rnatilmagan: pip install -r requirements.txt", verified=False)
        from .macos import battery_detail

        b = psutil.sensors_battery()
        if b is None:
            info: dict = {"present": False, "source": ""}
        else:
            pct = int(round(b.percent))
            plugged = bool(b.power_plugged)
            state = ("charged" if pct >= 100 else "charging") if plugged else "discharging"
            secs = b.secsleft
            known = isinstance(secs, (int, float)) and secs not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN)
            info = {"present": True, "percent": min(100, pct), "state": state,
                    "minutes_left": int(secs // 60) if known and not plugged and secs > 0 else None,
                    "source": "ac" if plugged else "battery"}
        return ExecResult(True, battery_detail(info), verified=True, data=info)

    def _do_reveal(self, a: Action) -> ExecResult:
        p = Path(a.path or "").expanduser()
        if not p.exists():
            return ExecResult(False, f"Topilmadi: {p}", verified=False)
        subprocess.run(["explorer", f"/select,{p}"], env=safe_env(), capture_output=True, timeout=10)   # explorer chiqish kodi ishonchsiz
        return ExecResult(True, str(p), verified=None)

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

