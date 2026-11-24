"""1-qadam: Mac muhiti auditi. Hech qanday ruxsat so'ramaydi, hech narsa yozib olmaydi, kalitlarni chiqarmaydi."""

from __future__ import annotations

import importlib.metadata as md
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import is_macos, save_result
from .macprobe import accessibility_trusted, microphone_status, screen_recording_allowed

PACKAGES = ("faster-whisper", "mlx-whisper", "mlx", "edge-tts", "sounddevice", "numpy", "mss", "pyautogui",
            "pyobjc-framework-Vision", "pyobjc-framework-Quartz", "pyobjc-framework-ApplicationServices",
            "pyobjc-framework-AVFoundation", "anthropic", "requests", "fastapi")

PERMISSION_HELP = {
    "microphone": "System Settings → Privacy & Security → Microphone → Terminal (yoki backend ishlayotgan ilova) ni yoqing.",
    "accessibility": "System Settings → Privacy & Security → Accessibility → Terminal ni yoqing (+ tugmasi bilan qo'shing).",
    "screen_recording": "System Settings → Privacy & Security → Screen & System Audio Recording → Terminal ni yoqing, "
                        "so'ng Terminal'ni qayta oching.",
}


def sh(cmd: list[str], timeout: float = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def package_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for p in PACKAGES:
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            out[p] = None
    return out


def speech_models(cache: Path | None = None) -> list[dict[str, Any]]:
    """Diskdagi Whisper modellari (Hugging Face keshi). Faqat nom va hajm."""
    root = cache or Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    found = []
    if not root.exists():
        return found
    for d in sorted(root.glob("models--*")):
        name = d.name.removeprefix("models--").replace("--", "/")
        if "whisper" not in name.lower():
            continue
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file() and not f.is_symlink())
        found.append({"repo": name, "size_mb": round(size / 1e6, 1)})
    return found


def hardware() -> dict[str, Any]:
    mem = sh(["sysctl", "-n", "hw.memsize"])
    translated = sh(["sysctl", "-n", "sysctl.proc_translated"])
    return {
        "macos_version": platform.mac_ver()[0] or None,
        "macos_build": sh(["sw_vers", "-buildVersion"]) or None,
        "hardware_model": sh(["sysctl", "-n", "hw.model"]) or None,
        "cpu": sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or None,
        "apple_silicon": platform.machine() == "arm64" or translated == "1",
        "python_arch": platform.machine(),
        # Apple Silicon'da x86 Python (Rosetta) ishlasa MLX ishlamaydi — ASR sekin protsessor rejimiga o'tadi
        "python_under_rosetta": translated == "1",
        "ram_gb": round(int(mem) / 2**30, 1) if mem.isdigit() else None,
        "cpu_cores": os.cpu_count(),
    }


def runtimes() -> dict[str, Any]:
    node = shutil.which("node")
    return {"python": platform.python_version(), "python_executable": sys.executable,
            "in_venv": sys.prefix != sys.base_prefix,
            "node": sh([node, "--version"]) if node else None,
            "npm": sh([shutil.which("npm") or "npm", "--version"]) if shutil.which("npm") else None,
            "ollama_cli": sh(["ollama", "--version"]) if shutil.which("ollama") else None}


def tts_voices(cfg) -> dict[str, Any]:
    from ..speech.tts import EDGE_VOICES, Speaker, edge_available, mac_voices

    voices = mac_voices() if is_macos() else {}
    by_locale: dict[str, list[str]] = {}
    for name, loc in voices.items():
        by_locale.setdefault(loc, []).append(name)
    sys_sp = Speaker("system", cfg.tts_rate, {"uz": cfg.voice_uz, "ru": cfg.voice_ru, "en": cfg.voice_en})
    return {
        "configured_engine": cfg.tts_engine,
        "mac_voice_count": len(voices),
        "mac_uz_voices": sorted(n for n, loc in voices.items() if loc.startswith("uz_")),
        "mac_voices_by_locale": {k: sorted(v) for k, v in sorted(by_locale.items())
                                 if k.split("_")[0] in ("uz", "ru", "en", "tr", "kk", "ky", "az")},
        "system_choice": {lg: sys_sp.voice_for(lg) for lg in ("uz", "ru", "en")},
        "edge_tts_installed": edge_available(),
        "edge_choice": {lg: EDGE_VOICES.get(lg) for lg in ("uz", "ru", "en")} if edge_available() else None,
        "note": "edge-tts internet talab qiladi va rasmiy bo'lmagan xizmat; o'zbekcha ovoz faqat shu orqali.",
    }


def microphone_device() -> dict[str, Any]:
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        return {"name": dev.get("name"), "default_samplerate": dev.get("default_samplerate"),
                "max_input_channels": dev.get("max_input_channels")}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{e.__class__.__name__}: {e}"}


def provider_info(cfg) -> dict[str, Any]:
    info: dict[str, Any] = {
        "provider": cfg.provider,
        "model": {"claude": cfg.claude_model, "ollama": cfg.ollama_model}.get(cfg.provider, "rules"),
        "has_anthropic_key": bool(cfg.anthropic_api_key),   # faqat bor/yo'q — kalit o'zi hech qachon yozilmaydi
        "ollama_url": cfg.ollama_url if cfg.provider == "ollama" else None,
    }
    if cfg.provider == "ollama":
        try:
            import requests

            r = requests.get(cfg.ollama_url.rstrip("/") + "/api/tags", timeout=3)
            names = [m.get("name") for m in r.json().get("models", [])]
            info["ollama_reachable"] = True
            info["ollama_models"] = names
            info["configured_model_installed"] = cfg.ollama_model in names or any(
                n.split(":")[0] == cfg.ollama_model.split(":")[0] for n in names if n)
        except Exception as e:  # noqa: BLE001
            info["ollama_reachable"] = False
            info["ollama_error"] = e.__class__.__name__
    try:
        from ..providers import make_provider

        p = make_provider(cfg)
        ok, detail = p.health()
        info.update(health_ok=ok, health_detail=detail[:200], supports_vision=p.supports_vision)
    except Exception as e:  # noqa: BLE001
        info.update(health_ok=False, health_detail=f"{e.__class__.__name__}")
    return info


def permissions() -> dict[str, Any]:
    perms = {"microphone": microphone_status(), "accessibility": accessibility_trusted(),
             "screen_recording": screen_recording_allowed(),
             "automation": "not_checked (macOS birinchi foydalanishda o'zi so'raydi)"}
    missing = []
    if perms["microphone"] in ("denied", "restricted"):
        missing.append("microphone")
    if perms["accessibility"] is False:
        missing.append("accessibility")
    if perms["screen_recording"] is False:
        missing.append("screen_recording")
    perms["missing"] = missing
    perms["how_to_fix"] = {k: PERMISSION_HELP[k] for k in missing}
    if perms["microphone"] in ("unknown", "not_determined"):
        perms["microphone_note"] = ("Holatni o'qib bo'lmadi yoki hali so'ralmagan. Birinchi yozuvda macOS o'zi "
                                    "so'raydi; aniq holat uchun: pip install pyobjc-framework-AVFoundation")
    return perms


def config_info(cfg) -> dict[str, Any]:
    return {"whisper_model": cfg.whisper_model, "stt_engine": cfg.stt_engine, "tts_engine": cfg.tts_engine,
            "confirm_risk": cfg.confirm_risk, "max_steps": cfg.max_steps, "fast_path": cfg.fast_path,
            "workspace": str(cfg.workspace), "screen_max_side": cfg.screen_max_side}


def audit(cfg) -> dict[str, Any]:
    from ..speech.stt import mlx_available

    return {
        "real_device": is_macos(),
        "hardware": hardware() if is_macos() else {"platform": platform.platform()},
        "runtimes": runtimes(),
        "packages": package_versions(),
        "speech_models_on_disk": speech_models(),
        "stt_engine_resolved": "mlx" if (cfg.stt_engine == "mlx" or (cfg.stt_engine == "auto" and mlx_available()))
        else "faster",
        "tts": tts_voices(cfg),
        "microphone_device": microphone_device(),
        "permissions": permissions() if is_macos() else {"note": "macOS emas"},
        "ai_provider": provider_info(cfg),
        "config": config_info(cfg),
    }


def main(args) -> int:
    from ..config import load_config

    cfg = load_config()
    data = audit(cfg)
    path = save_result("env", data)
    hw, perms = data["hardware"], data.get("permissions", {})
    print("\n=== Mac muhiti ===")
    for k in ("macos_version", "hardware_model", "cpu", "ram_gb", "apple_silicon", "python_under_rosetta"):
        if k in hw:
            print(f"  {k}: {hw[k]}")
    print(f"  python: {data['runtimes']['python']}  node: {data['runtimes']['node']}")
    print(f"  ASR: {data['stt_engine_resolved']} · {cfg.whisper_model} · diskda: "
          f"{', '.join(m['repo'] for m in data['speech_models_on_disk']) or 'model topilmadi'}")
    print(f"  TTS: {data['tts']['system_choice']} · edge-tts: {data['tts']['edge_tts_installed']}")
    ai = data["ai_provider"]
    print(f"  AI: {ai['provider']} · {ai['model']} · ishlayapti: {ai.get('health_ok')}")
    if hw.get("python_under_rosetta"):
        print("  ⚠ Python Rosetta (x86) ostida ishlayapti — MLX ishlamaydi. arm64 Python bilan venv qayta yarating.")
    for k in perms.get("missing", []):
        print(f"  ⚠ Ruxsat yo'q: {k} — {PERMISSION_HELP[k]}")
    print(f"\nSaqlandi: {path}")
    return 0
