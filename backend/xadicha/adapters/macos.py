"""macOS adapteri: `open`, AppleScript (osascript) va Accessibility; pyautogui — zaxira."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from ..redaction import safe_env
from ..models import Action
from .base import ExecResult, OSAdapter

_KEYMAP = {"cmd": "command", "ctrl": "ctrl", "control": "ctrl", "opt": "option", "alt": "option",
           "return": "enter", "esc": "escape"}


def osascript(script: str, timeout: float = 10) -> str:
    r = subprocess.run(["osascript", "-e", script], env=safe_env(), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "osascript xatosi")
    return r.stdout.strip()


_PMSET_PCT = re.compile(r"(\d{1,3})%")
_PMSET_STATE = re.compile(r"\d{1,3}%;\s*([^;]+?)\s*(?:;|$)", re.M)
_PMSET_LEFT = re.compile(r"(\d+):(\d{2})\s+remaining")


def parse_pmset(out: str) -> dict:
    """`pmset -g batt` chiqishi → {present, percent, state, minutes_left, source}.
    state: charging | discharging | charged | ac (quvvat manbaiga ulangan, lekin zaryadlanmayapti)."""
    source = "ac" if "'AC Power'" in out else "battery" if "'Battery Power'" in out else ""
    line = next((ln for ln in out.splitlines() if "InternalBattery" in ln or _PMSET_PCT.search(ln)), "")
    m = _PMSET_PCT.search(line)
    if not line or not m:
        return {"present": False, "source": source}   # Mac mini / iMac — batareya yo'q
    raw = (_PMSET_STATE.search(line).group(1).strip().lower() if _PMSET_STATE.search(line) else "")
    if raw in ("charging", "finishing charge"):
        state = "charging"
    elif raw == "discharging":
        state = "discharging"
    elif raw == "charged":
        state = "charged"
    elif "ac attached" in raw or "not charging" in raw or source == "ac":
        state = "ac"
    else:
        state = "discharging" if source == "battery" else "ac"
    left = _PMSET_LEFT.search(line)
    minutes = int(left.group(1)) * 60 + int(left.group(2)) if left else None
    if minutes == 0 or "no estimate" in line:
        minutes = None
    return {"present": True, "percent": min(100, int(m.group(1))), "state": state, "minutes_left": minutes,
            "source": source}


def battery_detail(info: dict) -> str:
    """Iz va tarix uchun qisqa matn (foydalanuvchiga aytiladigan javob — rule_based.battery_reply)."""
    if not info.get("present"):
        return "batareya topilmadi"
    left = info.get("minutes_left")
    return f"batareya: {info['percent']}%, {info['state']}" + (f", {left // 60}:{left % 60:02d} qoldi" if left else "")


class MacOSAdapter(OSAdapter):
    name = "macos"

    def _do_open_app(self, a: Action) -> ExecResult:
        app = (a.app or "").strip()
        r = subprocess.run(["open", "-a", app], env=safe_env(), capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return ExecResult(False, f"'{app}' ilovasi topilmadi", verified=False)
        # Dasturiy tekshiruv: ilova old planga chiqdimi (0,25 s oraliqda, 5 s gacha). Tezlashtirish faqat
        # real o'lchovdan keyin (validation: profile) — hozircha tekshiruv vaqti alohida o'lchanadi.
        tv = time.perf_counter()
        for _ in range(20):
            time.sleep(0.25)
            front = self.frontmost_app()
            if front and (app.lower() in front.lower() or front.lower() in app.lower()):
                return ExecResult(True, front, verified=True, verify_ms=int((time.perf_counter() - tv) * 1000))
        return ExecResult(True, f"ochildi, lekin old planda: {self.frontmost_app()}", verified=None,
                          verify_ms=int((time.perf_counter() - tv) * 1000))

    def _do_open_url(self, a: Action) -> ExecResult:
        url = a.url or ""
        if not url.lower().startswith(("http://", "https://", "mailto:", "tel:")):
            # Xavfsizlik qatlami buni allaqachon taqiqlaydi; bu — ikkinchi himoya (`open <yo'l>` ilovani ishga tushiradi)
            return ExecResult(False, "Faqat http/https manzillar ochiladi", verified=False)
        r = subprocess.run(["open", url], env=safe_env(), capture_output=True, text=True, timeout=15)
        return ExecResult(r.returncode == 0, a.url or "", verified=None if r.returncode == 0 else False)

    # --- tizim boshqaruvi: ovoz va yorqinlik (faqat sonli qiymatlar — ixtiyoriy matn AppleScript'ga tushmaydi) ---
    def _volume(self) -> int:
        return int(osascript("output volume of (get volume settings)", timeout=5))

    def _do_system(self, a: Action) -> ExecResult:
        c = a.control
        step = int(a.amount) if a.amount is not None else 10
        if c in ("volume_up", "volume_down", "volume_set"):
            cur = self._volume()
            target = step if c == "volume_set" else cur + step if c == "volume_up" else cur - step
            target = max(0, min(100, int(target)))
            osascript(f"set volume output volume {target} without output muted", timeout=5)
            tv = time.perf_counter()
            now = self._volume()
            return ExecResult(True, f"ovoz: {cur}% → {now}%", verified=abs(now - target) <= 2,
                              verify_ms=int((time.perf_counter() - tv) * 1000))
        if c in ("mute", "unmute"):
            want = c == "mute"
            osascript(f"set volume output muted {'true' if want else 'false'}", timeout=5)
            state = osascript("output muted of (get volume settings)", timeout=5).strip().lower() == "true"
            return ExecResult(True, "ovoz o'chirildi" if want else "ovoz yoqildi", verified=state == want)
        if c in ("brightness_up", "brightness_down"):
            # Yorqinlik tugmalari (key code 144/145) — Accessibility ruxsati kerak; har bosish ~6%
            presses = max(1, min(16, round(step / 6.25)))
            code = 144 if c == "brightness_up" else 145
            osascript(f'tell application "System Events"\nrepeat {presses} times\nkey code {code}\n'
                      f'delay 0.05\nend repeat\nend tell', timeout=10)
            return ExecResult(True, f"yorqinlik {'+' if code == 144 else '-'}{presses} qadam", verified=None)
        if c == "battery":
            return self._battery()
        if c == "screenshot":
            # Butun ekran → Desktop (ovozsiz, -x); faqat fayl yaratiladi, hech narsa yuborilmaydi
            out = Path.home() / "Desktop" / time.strftime("XADICHA Screenshot %Y-%m-%d %H.%M.%S.png")
            r = subprocess.run(["screencapture", "-x", str(out)], env=safe_env(), capture_output=True, text=True, timeout=15)
            ok = r.returncode == 0 and out.exists() and out.stat().st_size > 0
            return ExecResult(ok, str(out) if ok else (r.stderr.strip() or "screencapture xatosi (Ekran yozuvi ruxsati?)"),
                              verified=ok)
        return ExecResult(False, f"Noma'lum tizim boshqaruvi: {c}", verified=False)

    def _battery(self) -> ExecResult:
        """Batareya zaryadi — faqat aniq `pmset -g batt` (shell'siz, timeout bilan), faqat o'qish."""
        try:
            r = subprocess.run(["pmset", "-g", "batt"], env=safe_env(), capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as e:
            return ExecResult(False, f"batareya holatini o'qib bo'lmadi: {e.__class__.__name__}", verified=False)
        if r.returncode != 0:
            return ExecResult(False, "batareya holatini o'qib bo'lmadi (pmset)", verified=False)
        info = parse_pmset(r.stdout)
        return ExecResult(True, battery_detail(info), verified=True, data=info)

    def _do_reveal(self, a: Action) -> ExecResult:
        p = Path(a.path or "").expanduser()
        if not p.exists():
            return ExecResult(False, f"Topilmadi: {p}", verified=False)
        r = subprocess.run(["open", "-R", str(p)], env=safe_env(), capture_output=True, text=True, timeout=10)   # faqat ko'rsatadi
        return ExecResult(r.returncode == 0, str(p), verified=None if r.returncode == 0 else False)

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

    def front_window_title(self) -> str:
        try:
            return osascript('tell application "System Events" to get name of front window of '
                             '(first application process whose frontmost is true)', timeout=5)
        except Exception:  # noqa: BLE001 — oyna yo'q yoki Accessibility ruxsati yo'q
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
