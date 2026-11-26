"""Fayl qidiruvi — faqat workspace ichida, faqat o'qish (nomini qidiradi, tarkibni ochmaydi).

macOS: Spotlight (`mdfind -onlyin <workspace> -name <so'z>`), aks holda — chegaralangan os.walk.
Sezgir papkalar (~/.ssh, ~/Library ...) natijalarga kirmaydi.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess

from ..redaction import safe_env
import time
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "Library", ".Trash", ".cache", ".npm", ".ssh", ".gnupg",
             ".aws", ".config", "AppData"}


def _allowed(p: Path, root: Path) -> bool:
    from ..safety import _home_reason, is_inside

    return is_inside(str(p), root) and _home_reason(p, "find_file") is None and not any(
        part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts[:-1])


_KIND_EXT = {"pdf": {".pdf"}, "excel": {".xls", ".xlsx", ".csv", ".numbers"}, "word": {".doc", ".docx", ".rtf", ".pages"},
             "presentation": {".ppt", ".pptx", ".key"}, "image": {".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp"},
             "video": {".mp4", ".mov", ".mkv", ".avi"}}


def latest_downloads(root: Path, kind: str = "", limit: int = 5) -> list[Path]:
    """~/Downloads dagi eng yangi fayllar (o'zgartirilgan vaqti bo'yicha). Faqat workspace ichida, faqat o'qish."""
    d = Path.home() / "Downloads"
    if not d.is_dir() or not _allowed(d, root.expanduser().resolve()):
        return []
    exts = _KIND_EXT.get(kind)
    items = []
    for p in d.iterdir():
        if p.name.startswith(".") or p.suffix in (".crdownload", ".part", ".download") or not p.is_file():
            continue
        if exts and p.suffix.lower() not in exts:
            continue
        try:
            items.append((p.stat().st_mtime, p))
        except OSError:
            continue
    return [p for _, p in sorted(items, reverse=True)[:limit]]


def find_files(query: str, root: Path, limit: int = 15, timeout: float = 4.0, max_entries: int = 40000) -> list[Path]:
    q = query.strip().strip("\"'«»")
    if q.startswith(":latest-download"):
        return latest_downloads(root, q.split(":")[2] if q.count(":") >= 2 else "")
    if not q or len(q) > 120:
        return []
    root = root.expanduser().resolve()
    found: list[Path] = []
    if platform.system() == "Darwin":
        try:
            r = subprocess.run(["mdfind", "-onlyin", str(root), "-name", q], env=safe_env(), capture_output=True, text=True,
                               timeout=timeout)
            for line in r.stdout.splitlines():
                p = Path(line)
                if p.exists() and _allowed(p, root):
                    found.append(p)
                if len(found) >= limit:
                    return found
            if found:
                return found
        except (OSError, subprocess.TimeoutExpired):
            pass
    pat = re.compile(re.escape(q.lower()))
    t0, n = time.time(), 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in dirnames + filenames:
            n += 1
            if pat.search(name.lower()):
                p = Path(dirpath) / name
                if _allowed(p, root):
                    found.append(p)
                    if len(found) >= limit:
                        return found
        if n > max_entries or time.time() - t0 > timeout:
            break
    return found
