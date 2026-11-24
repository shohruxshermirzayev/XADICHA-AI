"""3-qadam: real TTS baholash — o'rnatilgan ovozlar va (sozlangan bo'lsa) edge-tts, siz tinglab baholaysiz.

  python -m xadicha.validate tts                # tavsiya etilgan nomzod ovozlar
  python -m xadicha.validate tts --all-voices   # o'rnatilgan barcha ovozlar (uzoq)
  python -m xadicha.validate tts --voices "Milena,Yelda"

Har bir juftlik (ovoz × ibora) uchun: dvigatel, aniq ovoz nomi va locale, sintez vaqti, audio fayl, sizning
bahoingiz (1–5) va izoh yoziladi. Ovoz til yorlig'iga qarab emas, baholarga qarab tavsiya qilinadi.
Mavjud bo'lmagan o'zbek ovozi "bor" deb ko'rsatilmaydi.
"""

from __future__ import annotations

import csv
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from . import RESULTS_DIR, VALIDATION_DIR, is_macos, save_result, stamp

PHRASES_FILE = VALIDATION_DIR / "tts_pronunciation.csv"
SCALE = "5 — tabiiy va to'g'ri; 4 — kichik xato; 3 — tushunarli, sezilarli xato; 2 — qiyin tushuniladi; 1 — noto'g'ri/tushunarsiz"
# O'zbek iboralarini sinash uchun yaqin tillar (o'zbek tizim ovozi odatda yo'q)
UZ_PROXY_LOCALES = ("uz_", "tr_", "kk_", "az_", "ky_")


def load_phrases(path: Path = PHRASES_FILE) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def candidates(cfg, installed: dict[str, str], all_voices: bool, names: list[str], edge: bool) -> list[dict[str, str]]:
    """Sinaladigan ovozlar: [{engine, voice, locale}] — faqat haqiqatan o'rnatilganlari."""
    from ..speech.tts import EDGE_VOICES, choose_mac_voice

    out: list[dict[str, str]] = []
    seen = set()

    def add(engine: str, voice: str | None, locale: str) -> None:
        if voice and (engine, voice) not in seen:
            seen.add((engine, voice))
            out.append({"engine": engine, "voice": voice, "locale": locale})

    if names:
        for n in names:
            if n in installed:
                add("system", n, installed[n])
            elif n in EDGE_VOICES.values() and edge:
                add("edge", n, n[:5].replace("-", "_"))
        return out
    if all_voices:
        for n, loc in sorted(installed.items()):
            add("system", n, loc)
    else:
        configured = {"uz": cfg.voice_uz, "ru": cfg.voice_ru, "en": cfg.voice_en}
        for lg in ("uz", "ru", "en"):
            v = choose_mac_voice(lg, configured.get(lg) or None, installed)   # ilova tanlaydigan ovoz
            if v:
                add("system", v, installed.get(v, lg))
        for n, loc in sorted(installed.items()):
            if loc.startswith(UZ_PROXY_LOCALES):
                add("system", n, loc)
    if edge:
        for v in EDGE_VOICES.values():
            add("edge", v, v[:5].replace("-", "_"))
    return out


def phrases_for(voice: dict[str, str], phrases: list[dict[str, str]]) -> list[dict[str, str]]:
    """Ovoz qaysi iboralarda sinaladi: o'z tili + aralash; o'zbekka yaqin ovozlar — o'zbek iboralari ham."""
    loc = voice["locale"].lower()
    lang = loc[:2]
    langs = {lang}
    if loc.startswith(UZ_PROXY_LOCALES):
        langs.add("uz")
    return [p for p in phrases if p["lang"] in langs or p["category"] == "mixed"]


def synth(voice: dict[str, str], text: str, out: Path, rate: int) -> tuple[bool, int, str]:
    """(ok, sintez_ms, xato). Faylga yozadi — keyin ijro etiladi (tinglash vaqti sintezga qo'shilmaydi)."""
    t0 = time.perf_counter()
    try:
        if voice["engine"] == "system":
            r = subprocess.run(["say", "-v", voice["voice"], "-r", str(rate), "-o", str(out), text],
                               capture_output=True, text=True, timeout=60)
            ok, err = r.returncode == 0 and out.exists(), r.stderr.strip()[:200]
        else:
            import asyncio

            import edge_tts

            async def go() -> None:
                await edge_tts.Communicate(text, voice["voice"]).save(str(out))

            asyncio.run(go())
            ok, err = out.exists() and out.stat().st_size > 0, ""
    except Exception as e:  # noqa: BLE001
        ok, err = False, f"{e.__class__.__name__}: {e}"[:200]
    return ok, round((time.perf_counter() - t0) * 1000), err


def audio_seconds(path: Path) -> float | None:
    try:
        out = subprocess.run(["afinfo", str(path)], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"estimated duration:\s*([\d.]+)", out)
    return round(float(m.group(1)), 2) if m else None


def summarize(items: list[dict[str, Any]], uz_native: list[str], edge: bool) -> dict[str, Any]:
    by_voice: dict[str, dict[str, Any]] = {}
    for it in items:
        key = f"{it['engine']}:{it['voice']}"
        v = by_voice.setdefault(key, {"engine": it["engine"], "voice": it["voice"], "locale": it["locale"],
                                      "scores": {}, "synth_ms": [], "errors": 0})
        if it.get("error"):
            v["errors"] += 1
        if it.get("synth_ms") is not None and not it.get("error"):
            v["synth_ms"].append(it["synth_ms"])
        if it.get("score") is not None:
            v["scores"].setdefault(it["lang"], []).append(it["score"])
            v["scores"].setdefault("cat:" + it["category"], []).append(it["score"])
    table = {}
    for key, v in by_voice.items():
        table[key] = {"engine": v["engine"], "voice": v["voice"], "locale": v["locale"], "errors": v["errors"],
                      "synth_ms_median": round(statistics.median(v["synth_ms"])) if v["synth_ms"] else None,
                      "mean_score": {k: round(statistics.mean(s), 2) for k, s in v["scores"].items()},
                      "n_rated": {k: len(s) for k, s in v["scores"].items()}}
    best = {}
    for lg in ("uz", "ru", "en"):
        rated = [(t["mean_score"][lg], k) for k, t in table.items() if t["n_rated"].get(lg, 0) >= 2]
        best[lg] = {"voice": max(rated)[1], "mean_score": max(rated)[0]} if rated else None
    return {"voices": table, "best_by_language": best,
            "uz_native_system_voice": uz_native or None,
            "uz_online_voice_configured": edge,
            "note": "Tavsiya faqat shu tinglovchining baholariga asoslangan (bitta baholovchi — cheklov)."}


def main(args) -> int:
    from ..config import load_config
    from ..speech.tts import edge_available, mac_voices

    if not is_macos():
        print("TTS sinovi faqat Mac'da.")
        return 2
    cfg = load_config()
    installed = mac_voices()
    edge = edge_available()
    names = [n.strip() for n in args.voices.split(",") if n.strip()]
    voices = candidates(cfg, installed, args.all_voices, names, edge)
    phrases = load_phrases()
    run_id = stamp()
    audio_dir = RESULTS_DIR / f"tts-{run_id}" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    uz_native = sorted(n for n, loc in installed.items() if loc.startswith("uz_"))
    print(f"O'rnatilgan ovozlar: {len(installed)} · o'zbek tizim ovozi: {uz_native or 'YO‘Q'} · edge-tts: {edge}")
    print(f"Sinaladi: {len(voices)} ta ovoz.  Baho: {SCALE}\n")
    items: list[dict[str, Any]] = []
    meta = {"real": True, "kind": "real TTS synthesis, single human rater", "installed_voice_count": len(installed),
            "candidates": voices, "audio_dir": str(audio_dir), "rate": cfg.tts_rate}
    try:
        for v in voices:
            print(f"\n=== {v['engine']} · {v['voice']} ({v['locale']}) ===")
            for p in phrases_for(v, phrases):
                ext = "aiff" if v["engine"] == "system" else "mp3"
                f = audio_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', v['voice'])}__{p['id']}.{ext}"
                ok, ms, err = synth(v, p["text"], f, cfg.tts_rate)
                rec: dict[str, Any] = {**v, "phrase_id": p["id"], "lang": p["lang"], "category": p["category"],
                                       "text": p["text"], "synth_ms": ms, "audio_file": f.name if ok else None,
                                       "error": err if not ok else None}
                if ok:
                    rec["audio_s"] = audio_seconds(f)
                    while True:
                        subprocess.run(["afplay", str(f)], timeout=120)
                        if args.no_rate:
                            break
                        print(f"   «{p['text']}»")
                        ans = input("   Baho [1-5], r=qayta, s=o'tkazish: ").strip().lower()
                        if ans == "r":
                            continue
                        rec["score"] = int(ans) if ans.isdigit() and 1 <= int(ans) <= 5 else None
                        if rec["score"] is not None and rec["score"] <= 3:
                            rec["note"] = input("   Nima noto'g'ri (masalan: o' → o, g' noto'g'ri)? ").strip()
                        break
                else:
                    print(f"   ✗ sintez xatosi: {err}")
                items.append(rec)
                save_result("tts", {**meta, "summary": summarize(items, uz_native, edge), "items": items}, run_id)
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
    summary = summarize(items, uz_native, edge)
    path = save_result("tts", {**meta, "summary": summary, "items": items}, run_id)
    print("\nEng yaxshi (sizning baholaringiz bo'yicha):", summary["best_by_language"])
    print(f"Saqlandi: {path}")
    return 0
