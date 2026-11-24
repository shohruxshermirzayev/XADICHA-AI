"""Xavfsizlik qatlami: harakat xavfini baholash va tasdiq siyosati.

Yakuniy xavf = max(qoida asosidagi baho, model taklif qilgan baho).
Model xavfni pasaytira olmaydi — faqat oshira oladi.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import RISK_ORDER, Action, RiskLevel, max_risk

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


def classify(action: Action, workspace: Path | None = None) -> RiskLevel:
    t = action.type
    if t == "delete_path":
        return RiskLevel.high
    if t in ("wait", "scroll"):
        return RiskLevel.low
    if t == "open_app":
        return RiskLevel.high if (action.app or "").strip().lower() in _SENSITIVE_APPS else RiskLevel.low
    if t == "open_url":
        url = (action.url or "").lower()
        if url.startswith(("file:", "javascript:")):
            return RiskLevel.high
        return RiskLevel.low
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
    try:
        p = Path(path).expanduser().resolve()
        return p == root.resolve() or root.resolve() in p.parents
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


_DANGEROUS_PATHS = re.compile(r"^(/|/system|/usr|/bin|/etc|/library|c:\\windows|c:\\program files)(/|\\|$)", re.I)


def blocked_reason(action: Action, workspace: Path) -> str | None:
    """Tasdiq bilan ham bajarilmaydigan harakatlar."""
    if action.type in ("create_folder", "create_file", "delete_path"):
        path = (action.path or "").strip()
        if not path:
            return "Yo'l ko'rsatilmagan."
        resolved = str(Path(path).expanduser())
        if _DANGEROUS_PATHS.match(resolved) and not is_inside(resolved, workspace):
            return "Tizim papkalariga yozish yoki ularni o'chirish taqiqlangan."
        if action.type == "delete_path" and Path(resolved).expanduser().resolve() == workspace.resolve():
            return "Ish papkasining o'zini o'chirib bo'lmaydi."
    return None
