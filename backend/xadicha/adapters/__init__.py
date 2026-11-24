from __future__ import annotations

import platform

from .base import DryRunAdapter, ExecResult, OSAdapter


def make_adapter(dry_run: bool = False) -> OSAdapter:
    if dry_run:
        return DryRunAdapter()
    system = platform.system()
    if system == "Darwin":
        from .macos import MacOSAdapter

        return MacOSAdapter()
    if system == "Windows":
        from .windows import WindowsAdapter

        return WindowsAdapter()
    return DryRunAdapter()


__all__ = ["DryRunAdapter", "ExecResult", "OSAdapter", "make_adapter"]
