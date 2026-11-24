"""Xavfsizlik qatlami: harakat xavfini baholash va tasdiq siyosati.

Yakuniy xavf = max(qoida asosidagi baho, model taklif qilgan baho).
Model xavfni pasaytira olmaydi — faqat oshira oladi.
"""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath
from urllib.parse import urlparse

from .models import RISK_ORDER, SYSTEM_CONTROLS, Action, RiskLevel, max_risk

# Xabar yuborish, o'rnatish, to'lov, o'chirish bilan bog'liq kalit so'zlar (uz/ru/en)
_SENSITIVE_WORDS = [
    # yuborish
    "send", "sent", "yubor", "отправ", "submit", "post", "tweet",
    # o'rnatish
    "install", "o'rnat", "o‘rnat", "установ", "brew ", "pip install", "npm install", "sudo",
    # to'lov
    "pay", "to'lov", "to‘lov", "оплат", "checkout", "buy", "sotib ol", "купи", "card", "karta",
    # o'chirish
    "delete", "o'chir", "o‘chir", "удал", "rm -", "trash", "format",
]

_SENSITIVE_HOTKEYS = [
    {"command", "delete"}, {"cmd", "delete"}, {"command", "backspace"},
    {"shift", "delete"}, {"command", "q"}, {"cmd", "q"}, {"alt", "f4"},
    {"command", "shift", "delete"},
]

_SENSITIVE_APPS = {"terminal", "iterm", "iterm2", "powershell", "cmd", "system settings",
                   "system preferences", "keychain access", "disk utility", "registry editor", "regedit"}


# Brauzerda xavfsiz ochiladigan sxemalar. Boshqa sxemalar (file:, smb:, x-apple-..., ilova yo'li) taqiqlanadi:
# `open <yo'l>` macOS'da ilovani ishga tushiradi, ya'ni open_url orqali Terminal'ni ochib bo'lardi.
_WEB_SCHEMES = {"http", "https"}
_SOFT_SCHEMES = {"mailto", "tel"}   # tashqi ilovani ochadi — o'rta xavf

# cmd.exe / qobiq maxsus belgilari: ilova nomida bo'lsa buyruq in'eksiyasi xavfi bor (Windows `cmd /c start`)
_SHELL_META = re.compile(r"[&|<>^%\"`$;\n\r]")

# Fayl amallari uchun taqiqlangan tizim papkalari (workspace ichida bo'lmasa)
_SYSTEM_ROOTS_POSIX = ("/system", "/usr", "/bin", "/sbin", "/etc", "/var", "/private", "/library",
                       "/applications", "/opt", "/dev", "/cores", "/boot", "/proc", "/sys")
_SYSTEM_ROOTS_WIN = ("c:\\windows", "c:\\program files", "c:\\program files (x86)", "c:\\programdata")

# Uy papkasidagi sezgir joylar: kalitlar, sozlamalar, avtoyuklanish — tasdiq bilan ham yozilmaydi/o'chirilmaydi
_HOME_SENSITIVE = (".ssh", ".gnupg", ".aws", ".config", ".kube", ".docker", ".zshrc", ".bashrc", ".bash_profile",
                   ".zprofile", ".profile", "Library", "AppData")
# Uy papkasidagi asosiy papkalarning O'ZI (ichidagi narsalar emas) o'chirilmaydi
_HOME_ROOT_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Movies", "Videos", "Applications")


def _is_windows_path(path: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", path)) or path.startswith("\\\\")


def resolve_path(path: str, workspace: Path) -> Path:
    """Yo'lni haqiqiy ko'rinishga keltiradi: ~ ochiladi, nisbiy yo'l workspace'ga nisbatan olinadi,
    `..` va symlinklar yechiladi (aylanib o'tishning oldini olish uchun)."""
    p = Path(path.strip()).expanduser()
    if not p.is_absolute():
        p = workspace.expanduser() / p
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return Path(str(p))


def check_url(url: str) -> tuple[RiskLevel, str | None]:
    """(xavf, taqiq sababi). Faqat http(s) erkin; mailto/tel — o'rta; qolgani taqiqlanadi."""
    u = (url or "").strip()
    if not u or u.startswith("-"):
        return RiskLevel.high, "Noto'g'ri manzil."
    scheme = urlparse(u).scheme.lower()
    if scheme in _WEB_SCHEMES:
        return RiskLevel.low, None
    if scheme in _SOFT_SCHEMES:
        return RiskLevel.medium, None
    given = scheme or "yo'l"
    return RiskLevel.high, f"Faqat http/https manzillar ochiladi (berilgan: {given})."


def classify(action: Action, workspace: Path | None = None) -> RiskLevel:
    t = action.type
    if t == "delete_path":
        return RiskLevel.high
    if t in ("wait", "scroll"):
        return RiskLevel.low
    if t == "system":
        # Ovoz va yorqinlik — qaytariladigan, zararsiz; tasdiqsiz darhol bajariladi
        return RiskLevel.low if action.control in SYSTEM_CONTROLS else RiskLevel.high
    if t == "open_app":
        return RiskLevel.high if (action.app or "").strip().lower() in _SENSITIVE_APPS else RiskLevel.low
    if t == "open_url":
        return check_url(action.url or "")[0]
    if t in ("create_folder", "create_file"):
        if workspace is not None and not is_inside(action.path or "", workspace):
            return RiskLevel.high
        return RiskLevel.medium
    if t == "hotkey":
        keys = {k.strip().lower() for k in (action.keys or [])}
        if any(keys == combo for combo in _SENSITIVE_HOTKEYS):
            return RiskLevel.high
        return RiskLevel.medium
    if t == "type_text":
        return RiskLevel.high if _has_sensitive_words(action.text or "") else RiskLevel.medium
    if t in ("click", "double_click"):
        return RiskLevel.medium
    return RiskLevel.medium


def _has_sensitive_words(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _SENSITIVE_WORDS)


def is_inside(path: str, root: Path) -> bool:
    if _is_windows_path(path) != _is_windows_path(str(root)):
        return False
    try:
        p = resolve_path(path, root)
        r = root.expanduser().resolve()
        return p == r or r in p.parents
    except (OSError, ValueError):
        return False


def final_risk(action: Action, proposed: RiskLevel, workspace: Path | None = None,
               context: str = "") -> RiskLevel:
    """Qoida + model + kontekst (masalan, kutilgan natijada "yuborish" bo'lsa)."""
    risk = max_risk(classify(action, workspace), proposed)
    if action.type in ("click", "double_click", "hotkey") and _has_sensitive_words(context):
        risk = RiskLevel.high
    return risk


def needs_confirmation(risk: RiskLevel, threshold: str) -> bool:
    try:
        th = RiskLevel(threshold)
    except ValueError:
        th = RiskLevel.medium
    return RISK_ORDER[risk] >= RISK_ORDER[th]


def _system_reason(resolved: Path, raw: str) -> str | None:
    if _is_windows_path(raw):
        low = str(PureWindowsPath(raw)).lower().rstrip("\\")
        if any(low == r or low.startswith(r + "\\") for r in _SYSTEM_ROOTS_WIN) or re.fullmatch(r"[a-z]:", low):
            return "Tizim papkalariga yozish yoki ularni o'chirish taqiqlangan."
        return None
    low = str(resolved).lower()
    if low == "/" or any(low == r or low.startswith(r + "/") for r in _SYSTEM_ROOTS_POSIX):
        return "Tizim papkalariga yozish yoki ularni o'chirish taqiqlangan."
    return None


def _home_reason(resolved: Path, action_type: str) -> str | None:
    home = Path.home().resolve()
    if resolved == home:
        return "Uy papkasining o'zi bilan ishlash taqiqlangan."
    try:
        rel = resolved.relative_to(home)
    except ValueError:
        return None
    first = rel.parts[0] if rel.parts else ""
    if first in _HOME_SENSITIVE:
        return f"~/{first} — sezgir papka (kalitlar, sozlamalar), u yerda fayl amallari taqiqlangan."
    if action_type == "delete_path" and len(rel.parts) == 1 and first in _HOME_ROOT_DIRS:
        return f"~/{first} papkasining o'zini o'chirib bo'lmaydi."
    return None


def blocked_reason(action: Action, workspace: Path) -> str | None:
    """Tasdiq bilan ham bajarilmaydigan harakatlar."""
    if action.type == "system":
        if action.control not in SYSTEM_CONTROLS:
            return "Noma'lum tizim boshqaruvi."
        if action.amount is not None and not (0 <= action.amount <= 100):
            return "Qiymat 0–100 oralig'ida bo'lishi kerak."
        return None
    if action.type == "open_url":
        return check_url(action.url or "")[1]
    if action.type == "open_app":
        app = (action.app or "").strip()
        if not app:
            return "Ilova nomi ko'rsatilmagan."
        if _SHELL_META.search(app) or app.startswith("-"):
            return "Ilova nomida ruxsat etilmagan belgilar bor."
        return None
    if action.type in ("create_folder", "create_file", "delete_path"):
        raw = (action.path or "").strip()
        if not raw:
            return "Yo'l ko'rsatilmagan."
        resolved = resolve_path(raw, workspace)
        inside = is_inside(raw, workspace)
        if not inside:
            reason = _system_reason(resolved, raw)
            if reason:
                return reason
        reason = _home_reason(resolved, action.type)
        if reason:
            return reason
        if action.type == "delete_path" and resolved == workspace.expanduser().resolve():
            return "Ish papkasining o'zini o'chirib bo'lmaydi."
    return None
