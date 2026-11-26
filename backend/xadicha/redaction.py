"""Maxfiy qiymatlarni yashirish: loglar, xato matnlari, API javoblari va subprocess muhiti uchun.

Ikki himoya qatlami:
  1) ma'lum formatlar (Anthropic `sk-ant-…`, Google `AIza…`, URL'dagi `key=…`, `Bearer …`, `api_key=…`);
  2) konfiguratsiyadan o'qilgan kalitlarning AYNAN qiymati (format qanday bo'lishidan qat'i nazar).
"""

from __future__ import annotations

import os
import re
import threading

_SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "sk-***"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "AIza***"),                       # Google API kaliti
    (re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|token)=)[^&\s\"'#]+"), r"\1***"),   # URL parametri
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1***"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|parol)\s*[=:]\s*)\S+"), r"\1***"),
    (re.compile(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]{32,}"), "data:image/***"),
]

_known: set[str] = set()
_lock = threading.Lock()

# Subprocess'larga (open, osascript, say, mdfind…) uzatilmaydigan muhit o'zgaruvchilari
_SENSITIVE_ENV = re.compile(r"(?i)(?:API_KEY|_TOKEN|SECRET|PASSWORD|CREDENTIAL)")
_SENSITIVE_NAMES = {"GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                    "GOOGLE_APPLICATION_CREDENTIALS"}


def register_secret(value: str | None) -> None:
    """Konfiguratsiyadagi kalitni ro'yxatga oladi — keyin u har qanday matnda `***` bilan almashtiriladi."""
    v = (value or "").strip()
    if len(v) >= 8:   # juda qisqa qiymat oddiy so'zlarni buzmasin
        with _lock:
            _known.add(v)


def redact(text: str) -> str:
    """Log va xato matnlaridan kalit, token va rasm ma'lumotlarini olib tashlaydi."""
    if not text:
        return text
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for v in known:
        if v in text:
            text = text.replace(v, "***")
    for pat, rep in _SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


def safe_env() -> dict[str, str]:
    """Joriy muhitning nusxasi — API kalitlari va tokenlarsiz (tashqi dasturlar ularni meros qilib olmasin)."""
    return {k: v for k, v in os.environ.items() if k not in _SENSITIVE_NAMES and not _SENSITIVE_ENV.search(k)}
