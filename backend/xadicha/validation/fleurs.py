"""Ochiq inson nutqi to'plami — Google FLEURS (CC BY 4.0) bilan baholash (foydalanuvchi yozuvisiz).

  python -m xadicha.validate fleurs --download --split dev  --per-lang 60   # VAD sozlash uchun (dev)
  python -m xadicha.validate fleurs --download --split test --per-lang 30   # yakuniy baholash (test)
  python -m xadicha.validate fleurs --vad  --split dev                       # VAD (nutqni sezish) — mahalliy, API'siz
  python -m xadicha.validate fleurs --stt  --split test --providers whisper,gemini-live

FLEURS — ko'p ishtirokchili, rozilik bilan yozilgan haqiqiy inson nutqi (o'qilgan Wikipedia gaplari, uz/ru/en).
Manba: https://huggingface.co/datasets/google/fleurs (Conneau va boshq., 2022), litsenziya CC BY 4.0.
Cheklov: bu BUYRUQ emas, o'qilgan gaplar — niyat/obyekt aniqligi o'lchanmaydi; foydalanuvchining o'z ovozi,
mikrofoni va xonasi o'rnini bosmaydi. Audio git'ga qo'shilmaydi (backend/data/ — .gitignore).
Qoida: VAD parametrlari faqat `dev` da sozlanadi; `test` — faqat yakuniy o'lchov.
"""

from __future__ import annotations

import csv
import json
import re
import struct
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from . import BACKEND_DIR, VALIDATION_DIR, save_result

BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
LANGS = {"uz": "uz_uz", "ru": "ru_ru", "en": "en_us"}
DATA_DIR = BACKEND_DIR / "data" / "fleurs"
SPLITS = ("dev", "test")
_WAV = re.compile(r"^\d{5,25}\.wav$")
UA = {"User-Agent": "xadicha-eval/1.0"}


def manifest_path(split: str) -> Path:
    return VALIDATION_DIR / f"fleurs_{split}_sample.csv"


def parse_tsv(text: str) -> dict[str, dict[str, str]]:
    """FLEURS tsv: id, fayl, xom matn, normallashgan matn, harflar, namunalar soni, jins."""
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        p = line.split("\t")
        if len(p) < 7 or not _WAV.match(p[1]):
            continue
        rows[p[1]] = {"sentence_id": p[0], "file": p[1], "raw": p[2], "text": p[3].strip(),
                      "samples": p[-2], "gender": p[-1].strip()}
    return rows


def _get(url: str, timeout: float = 60.0):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)  # noqa: S310 — faqat BASE


def download(split: str, per_lang: int, langs: list[str], max_s: float = 25.0) -> Path:
    """Arxivni oqim bilan o'qiydi va dastlabki `per_lang` ta mos yozuvni oladi (butun arxiv yuklanmaydi)."""
    out_rows: list[dict[str, str]] = []
    for lang in langs:
        code = LANGS[lang]
        with _get(f"{BASE}/{code}/{split}.tsv") as r:
            meta = parse_tsv(r.read().decode("utf-8"))
        dest = DATA_DIR / code / split
        dest.mkdir(parents=True, exist_ok=True)
        got, seen = 0, set()
        with _get(f"{BASE}/{code}/audio/{split}.tar.gz", timeout=120) as r, tarfile.open(fileobj=r, mode="r|gz") as tf:
            for m in tf:
                name = Path(m.name).name
                if not m.isfile() or not _WAV.match(name) or name not in meta:
                    continue
                row = meta[name]
                if row["sentence_id"] in seen or int(row["samples"] or 0) > max_s * 16000:
                    continue   # bir gapning boshqa o'quvchisi yoki juda uzun yozuv — o'tkazamiz
                data = tf.extractfile(m).read()
                (dest / name).write_bytes(data)   # faqat raqamli nom — yo'l chetlab o'tilmaydi
                seen.add(row["sentence_id"])
                out_rows.append({"lang": lang, "split": split, **{k: row[k] for k in
                                 ("file", "sentence_id", "text", "raw", "gender", "samples")}})
                got += 1
                if got >= per_lang:
                    break
        print(f"{code}/{split}: {got} ta yozuv → {dest}")
    path = manifest_path(split)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["lang", "split", "file", "sentence_id", "gender", "samples", "text", "raw"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"Ro'yxat: {path}")
    return path


def load_manifest(split: str, langs: list[str] | None = None, limit: int = 0) -> list[dict[str, str]]:
    with manifest_path(split).open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not langs or r["lang"] in langs]
    if limit:
        by: dict[str, list] = {}
        for r in rows:
            by.setdefault(r["lang"], []).append(r)
        rows = [r for rs in by.values() for r in rs[:limit]]
    return rows


def read_riff(data: bytes) -> np.ndarray:
    """16 kHz mono WAV: PCM 16-bit (1) yoki IEEE float 32-bit (3, FLEURS shu formatda) — sof, testlanadi."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("WAV emas")
    pos, fmt, pcm = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            pcm = body
        pos += 8 + size + (size & 1)
    if not fmt or pcm is None:
        raise ValueError("fmt/data bo'lagi yo'q")
    tag, ch, rate, _, _, bits = fmt
    if ch != 1 or rate != 16000:
        raise ValueError(f"16 kHz mono kerak (keldi: {rate} Hz, {ch} kanal)")
    if tag == 3 and bits == 32:
        return np.frombuffer(pcm[: len(pcm) // 4 * 4], dtype="<f4").astype(np.float32)
    if tag == 1 and bits == 16:
        return np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    raise ValueError(f"qo'llab-quvvatlanmaydigan WAV formati: {tag}/{bits}")


def read_audio(row: dict[str, str]) -> np.ndarray:
    return read_riff((DATA_DIR / LANGS[row["lang"]] / row["split"] / row["file"]).read_bytes())


# ---------- VAD (nutqni sezish) — mahalliy, API'siz ----------

def frame_rms(audio: np.ndarray, frame: int = 320) -> np.ndarray:
    n = len(audio) // frame * frame
    return np.sqrt(np.mean(np.square(audio[:n].reshape(-1, frame)), axis=1)) if n else np.zeros(0)


def oracle_speech(audio: np.ndarray) -> tuple[float, float] | None:
    """Butun yozuvni ko'rib (oflayn) nutq boshi/oxiri — VAD'ni baholash uchun taxminiy etalon."""
    rms = frame_rms(audio)
    if not rms.size:
        return None
    thr = max(3 * float(np.percentile(rms, 10)), 0.1 * float(np.percentile(rms, 99)), 0.002)
    idx = np.nonzero(rms > thr)[0]
    return (idx[0] * 0.02, (idx[-1] + 1) * 0.02) if idx.size else None


# Holatlar: cho'qqi darajasi (MacBook mikrofoni: yaqindan ≈ 0.5, uzoqroqdan ≈ 0.12 — foydalanuvchi yozuvlarida
# 0.11–0.77 o'lchangan), nutqdan oldingi jimlik va qo'shimcha shovqin (SNR, dB)
KINDS = {"normal": (0.5, 0.8, None), "quiet_mic": (0.12, 0.8, None), "immediate": (0.3, 0.05, None),
         "noisy": (0.5, 0.8, 15.0),
         # Juda past kirish darajasi (FLEURS en yozuvlarining 19/30 i shunday: cho'qqi < 0.05)
         "very_quiet": (0.02, 0.8, None),
         # Buyruq uzunligidagi nutq (FLEURS gaplari ≈ 10 s, buyruqlar 1.5–2.5 s): gapning dastlabki 2 soniyasi
         "short": (0.5, 0.8, None), "short_immediate": (0.3, 0.05, None), "short_quiet": (0.12, 0.8, None)}
SHORT_S = 2.0


def background(clean: np.ndarray, scale: float, o: tuple[float, float]) -> float:
    """Xona foni = yozuvning nutqdan OLDINGI qismi (bir xona — oldin va keyin bir xil shovqin). Nutq gapdan
    oldingi jimliksiz boshlansa — eng sokin 5% kadr. (Birinchi versiyada fon gap ichidagi 10% kadrdan olingan va
    oldingi jimlikdan 2–6 barobar baland chiqqan — sun'iy nomuvofiqlik, 2026-11-27 da tuzatildi.)"""
    pre = clean[:int(o[0] * 16000)] * scale
    if len(pre) >= 1600:
        return max(1e-4, float(np.median(frame_rms(pre))))
    return max(1e-4, float(np.percentile(frame_rms(clean * scale), 5)))


def scenario(clean: np.ndarray, kind: str, rng: np.random.Generator) -> tuple[np.ndarray, tuple[float, float]] | None:
    """Haqiqiy foydalanish holati: (audio, (nutq boshi, nutq oxiri) soniyada). Nutq topilmasa — None.

    Fon: yozuvning o'z shovqini darajasida (eng sokin 10% kadr) — raqamli nol emas. "immediate": yozuvdagi
    jimlik kesiladi, nutq Enter bosilishi bilan (0.05 s) boshlanadi — kalibrlash nutqqa to'g'ri keladi.
    """
    o = oracle_speech(clean / max(1e-6, float(np.abs(clean).max())))
    if not o:
        return None
    peak, lead, snr = KINDS[kind]
    s0 = max(0, int((o[0] - 0.15) * 16000))
    if kind.startswith("short") and o[1] - o[0] > SHORT_S:
        o = (o[0], o[0] + SHORT_S)
        body = clean[s0:int(o[1] * 16000)].copy()
        body[-800:] *= np.linspace(1, 0, min(800, len(body)), dtype=np.float32)   # 50 ms so'nish
    else:
        body = clean[s0:int(min(len(clean), (o[1] + 0.3) * 16000))]
    scale = peak / max(1e-6, float(np.abs(body).max()))
    body = body * scale
    bg = background(clean, scale, o)
    noise = lambda n, lvl: (rng.standard_normal(n) * lvl).astype(np.float32)  # noqa: E731
    start = lead + (o[0] - s0 / 16000)
    audio = np.concatenate([noise(int(lead * 16000), bg), body, noise(3 * 16000, bg)])
    if snr is not None:
        sp = frame_rms(audio)
        level = float(np.sqrt(np.mean(np.square(sp[sp > np.percentile(sp, 50)])))) / 10 ** (snr / 20)
        audio = audio + noise(len(audio), level)
    return audio.astype(np.float32), (round(start, 2), round(start + (o[1] - o[0]), 2))


SILENCE_KINDS = ("silence", "silence_ramp", "silence_clicks", "quiet_room_clicks", "quiet_room_ramp")


def silence_scenario(clean: np.ndarray, kind: str, rng: np.random.Generator, seconds: float = 7.0) -> np.ndarray:
    """Nutqsiz holat (yozuvning o'z fon darajasida): barqaror shovqin, sekin ortuvchi shovqin (konditsioner yoqildi),
    klaviatura taqillashi. VAD bu yerda nutq "eshitmasligi" kerak."""
    peak = 0.02 if kind.startswith("quiet_room") else 0.5   # past kirish darajasidagi xona (juda sokin fon)
    scale = peak / max(1e-6, float(np.abs(clean).max()))
    o = oracle_speech(clean * scale) or (0.0, 0.0)
    bg = background(clean, scale, o)
    n = int(seconds * 16000)
    audio = rng.standard_normal(n).astype(np.float32) * bg
    if kind.endswith("_ramp"):                   # 1–3 s oralig'ida fon 4 barobar ortadi
        gain = np.clip((np.arange(n) / 16000 - 1.0) / 2.0, 0, 1) * 3 + 1
        audio = audio * gain.astype(np.float32)
    elif kind.endswith("_clicks"):               # 30 ms li 3 ta taqillash (fondan 20 barobar baland)
        for t in (1.5, 3.2, 4.8):
            i = int(t * 16000)
            audio[i:i + 480] += rng.standard_normal(480).astype(np.float32) * bg * 20
    return audio


def run_endpointer(audio: np.ndarray, chunk: int, max_s: float, **kw) -> dict[str, Any]:
    from ..speech.stt import Endpointer

    ep = Endpointer(**kw)
    stop_t = None
    for i in range(0, len(audio) - chunk + 1, chunk):
        c = audio[i:i + chunk]
        if ep.feed(float(np.sqrt(np.mean(c * c))), chunk / 16000):
            stop_t = ep.t
            break
        if ep.t >= max_s:
            break
    return {"reason": ep.reason or "max_seconds", "stop_s": round(stop_t if stop_t is not None else ep.t, 2),
            "heard": ep.heard, "first_s": ep.first_speech_t, "speech_s": round(ep.speech_total, 2)}


def vad_eval(rows: list[dict[str, str]], chunks=(1024, 512, 160), endpointer_kw: dict | None = None,
             seed: int = 7) -> dict[str, Any]:
    """Har yozuv × holat × bo'lak o'lchami: nutq sezildimi, erta kesilmadimi, gap tugagach qancha kutdi."""
    rng = np.random.default_rng(seed)
    per: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        clean = read_audio(row)
        for kind in KINDS:
            sc = scenario(clean, kind, rng)
            if sc is None:
                continue
            audio, (_start, end) = sc
            for ch in chunks:
                r = run_endpointer(audio, ch, max_s=end + 6.0, **(endpointer_kw or {}))
                r.update(lang=row["lang"], kind=kind, chunk=ch, speech_end_s=round(end, 2),
                         cut_early=bool(r["reason"] == "silence" and r["stop_s"] < end - 0.5),
                         eos_delay_s=round(r["stop_s"] - end, 2) if r["reason"] == "silence" else None)
                per.setdefault(f"{kind}/{ch}", []).append(r)
        for kind in SILENCE_KINDS:
            audio = silence_scenario(clean, kind, rng)
            for ch in chunks:
                r = run_endpointer(audio, ch, max_s=7.0, **(endpointer_kw or {}))
                r.update(lang=row["lang"], kind=kind, chunk=ch)
                per.setdefault(f"{kind}/{ch}", []).append(r)
    summary = {}
    for key, rs in per.items():
        n = len(rs)
        if key.split("/")[0] in SILENCE_KINDS:
            summary[key] = {"n": n, "false_speech_pct": round(100 * sum(r["heard"] for r in rs) / n, 1)}
            continue
        ok = [r for r in rs if r["reason"] == "silence" and not r["cut_early"]]
        delays = sorted(r["eos_delay_s"] for r in ok)
        summary[key] = {"n": n, "detected_pct": round(100 * sum(r["heard"] for r in rs) / n, 1),
                        "endpoint_ok_pct": round(100 * len(ok) / n, 1),
                        "cut_early_pct": round(100 * sum(bool(r["cut_early"]) for r in rs) / n, 1),
                        "no_speech_pct": round(100 * sum(r["reason"] == "no_speech" for r in rs) / n, 1),
                        "eos_delay_p50_s": float(delays[len(delays) // 2]) if delays else None,
                        "eos_delay_p95_s": float(delays[min(len(delays) - 1, int(0.95 * len(delays)))]) if delays else None}
    return {"summary": summary, "items": [r for rs in per.values() for r in rs]}


# ---------- STT (WER/CER, til aniqlash) ----------

def _transcribe_once(li, audio: np.ndarray, lang: str) -> tuple[str, str, str]:
    """(matn, til, xato). Oqimli STT xatoni istisno bilan emas, holat bilan qaytaradi ("error:…") — u ham xato:
    bunday yozuv WER'ga kirmaydi (aks holda ulanish uzilishi "100% xato tanish" bo'lib ko'rinardi)."""
    from ..redaction import redact

    try:
        tr = li.transcribe(audio, None, prior=lang)
    except Exception as e:  # noqa: BLE001 — bitta yozuv xatosi butun baholashni to'xtatmasin
        return "", "", redact(f"{type(e).__name__}: {e}")[:200]
    status = getattr(li, "last_status", "") or ""
    if status.startswith("error") and not tr.text:
        return "", "", status[:200]
    return tr.text, tr.language, ""


def stt_eval(rows: list[dict[str, str]], providers: list[str], cfg, pause_s: float = 0.0) -> dict[str, Any]:
    from ..lang import refine_asr_language
    from ..metrics import cer, wer
    from .speech import make_provider

    out: dict[str, Any] = {}
    for name in providers:
        li = make_provider(name, cfg)
        if hasattr(li, "warmup"):
            li.warmup()
        items = []
        for row in rows:
            audio = read_audio(row)
            retried = False
            for attempt in range(2):   # ulanish/javob xatosida bir marta qayta urinish (B3 alohida sanaladi)
                t0 = time.perf_counter()
                hyp, lang, err = _transcribe_once(li, audio, row["lang"])
                ms = round((time.perf_counter() - t0) * 1000)
                if not err or attempt:
                    break
                retried = True
                time.sleep(max(pause_s, 3.0))
            final = refine_asr_language(hyp, lang, None, row["lang"]) if hyp else lang
            ref = row["text"]
            items.append({"provider": name, "lang": row["lang"], "file": row["file"], "reference": ref,
                          "hypothesis": hyp, "wer": round(wer(ref, hyp), 4), "cer": round(cer(ref, hyp), 4),
                          "lid_ok": final == row["lang"], "asr_ms": ms, "audio_s": round(len(audio) / 16000, 2),
                          "status": getattr(li, "last_status", ""), "error": err, "retried": retried})
            print(f"  {name:12} {row['lang']} WER={items[-1]['wer']:.2f} til={final or '-'} {ms} ms "
                  f"{(err or '')[:60]}", flush=True)
            if pause_s:
                time.sleep(pause_s)
        out[name] = {"summary": stt_summary(items), "items": items}
    return out


def stt_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    def block(rs):
        ok = [r for r in rs if not r["error"]]
        if not rs:
            return {}
        server = [r for r in ok if str(r.get("status", "")).startswith("server")]
        local = [r for r in ok if str(r.get("status", "")).startswith("local")]
        extra = {}
        if server or local:
            extra = {"n_server_final": len(server), "n_local": len(local),
                     "wer_server_final": round(sum(r["wer"] for r in server) / len(server), 4) if server else None}
        return {**extra, "n": len(rs), "errors": len(rs) - len(ok), "retried": sum(bool(r.get("retried")) for r in rs),
                "wer_mean": round(sum(r["wer"] for r in ok) / len(ok), 4) if ok else None,
                "cer_mean": round(sum(r["cer"] for r in ok) / len(ok), 4) if ok else None,
                "lid_pct": round(100 * sum(r["lid_ok"] for r in ok) / len(ok), 1) if ok else None,
                "asr_ms_p50": sorted(r["asr_ms"] for r in ok)[len(ok) // 2] if ok else None}
    return {"overall": block(items), **{lang: block([r for r in items if r["lang"] == lang]) for lang in LANGS}}


def main(args) -> int:
    langs = [x for x in (args.langs or "uz,ru,en").split(",") if x in LANGS]
    if args.download:
        download(args.split, args.per_lang, langs)
    if not (args.vad or args.stt):
        return 0
    if not manifest_path(args.split).exists():
        print(f"Avval yuklab oling: python -m xadicha.validate fleurs --download --split {args.split}")
        return 2
    rows = load_manifest(args.split, langs, args.limit)
    res: dict[str, Any] = {"dataset": "google/fleurs (CC BY 4.0)", "split": args.split, "n_clips": len(rows),
                           "real_human_speech": True, "kind": "read sentences (not commands)",
                           "note": "VAD holatlari (sokin mikrofon, darhol gapirish, shovqin) asl yozuvga sun'iy qo'shilgan"}
    if args.vad:
        res["vad"] = vad_eval(rows)
        print(json.dumps(res["vad"]["summary"], ensure_ascii=False, indent=1))
    if args.stt:
        from ..config import load_config

        providers = [p.strip() for p in args.providers.split(",") if p.strip()]
        res["stt"] = stt_eval(rows, providers, load_config(), pause_s=args.pause)
        for name, block in res["stt"].items():
            print(name, json.dumps(block["summary"], ensure_ascii=False))
    path = save_result(f"fleurs_{args.split}", res)
    print(f"Saqlandi: {path}")
    return 0
