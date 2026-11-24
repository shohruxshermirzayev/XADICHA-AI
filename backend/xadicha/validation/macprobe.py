"""Agentdan MUSTAQIL tekshiruvlar (macOS). Har biri faqat o'qiydi; o'qib bo'lmasa None qaytaradi.

Brauzer manzili, Finder tanlovi va Notes uchun macOS "Automation" ruxsatini so'raydi — bu oynani
macOS o'zi ko'rsatadi, foydalanuvchi o'zi tanlaydi. Bu yerda ruxsat chetlab o'tilmaydi.
"""

from __future__ import annotations

import ctypes
import platform
import subprocess

_BROWSERS = {
    "Safari": 'tell application "Safari" to get URL of current tab of front window',
    "Google Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
    "Microsoft Edge": 'tell application "Microsoft Edge" to get URL of active tab of front window',
    "Arc": 'tell application "Arc" to get URL of active tab of front window',
}


def _osa(script: str, timeout: float = 6) -> str | None:
    if platform.system() != "Darwin":
        return None
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def frontmost_app() -> str | None:
    return _osa('tell application "System Events" to get name of first application process whose frontmost is true')


def browser_url(browser: str | None = None) -> str | None:
    """Old plandagi (yoki berilgan) brauzerning joriy sahifa manzili."""
    name = browser or frontmost_app() or ""
    script = _BROWSERS.get(name)
    if script is None:
        for b, s in _BROWSERS.items():
            if b in name:
                script = s
                break
    return _osa(script) if script else None


def finder_selection() -> str | None:
    return _osa('tell application "Finder" to get POSIX path of (item 1 of (get selection) as alias)')


def notes_first_title() -> str | None:
    return _osa('tell application "Notes" to get name of first note')


def output_volume() -> int | None:
    v = _osa("output volume of (get volume settings)")
    return int(v) if v and v.isdigit() else None


def accessibility_trusted() -> bool | None:
    """AXIsProcessTrusted — so'rov oynasini CHIQARMAYDI, faqat holatni o'qiydi."""
    if platform.system() != "Darwin":
        return None
    try:
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except (OSError, AttributeError):
        return None


def screen_recording_allowed() -> bool | None:
    """CGPreflightScreenCaptureAccess — so'rov oynasini CHIQARMAYDI (macOS 10.15+)."""
    if platform.system() != "Darwin":
        return None
    try:
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        fn = lib.CGPreflightScreenCaptureAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except (OSError, AttributeError):
        return None


def microphone_status() -> str:
    """authorized | denied | restricted | not_determined | unknown. So'rov oynasini CHIQARMAYDI.
    Ruxsat backend ishlayotgan ilovaga (odatda Terminal) tegishli."""
    if platform.system() != "Darwin":
        return "unknown"
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio  # pyobjc-framework-AVFoundation
    except ImportError:
        return "unknown"
    try:
        code = int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio))
    except Exception:  # noqa: BLE001
        return "unknown"
    return {0: "not_determined", 1: "restricted", 2: "denied", 3: "authorized"}.get(code, "unknown")
