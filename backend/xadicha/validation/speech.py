"""2-qadam: real mikrofon va ASR sinovi — ALOHIDA, oldindan ko'rilmagan to'plamda (validation/speech_validation_set.csv).

  python -m xadicha.validate speech                       # hammasini yozish (≈64 ta, har biri bir necha soniya)
  python -m xadicha.validate speech --only uz_latn,mixed  # faqat ba'zi guruhlar
  python -m xadicha.validate speech --rescore validation/results/speech-<vaqt> --models small,large-v3-turbo
      # saqlangan HAQIQIY yozuvlarni boshqa model/dvigatel bilan qayta baholash (mikrofon kerak emas)

O'lchanadi: WER, CER, til aniqlash, niyat va obyekt aniqligi, ASR vaqti, nutq tugashini sezish kechikishi,
xato turlari (tushib qolgan so'z, noto'g'ri qo'shimcha, til chalkashligi, ilova nomi xatosi, kesilish,
jimlikda "eshitilgan" matn). Audio to'qib chiqarilmaydi — faqat siz yozgan ovoz.
127 buyruqli korpus bu yerda ISHLATILMAYDI (u sozlashda ishlatilgan, regressiya testi).
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from . import RESULTS_DIR, VALIDATION_DIR, is_macos, save_result, stamp
from ..metrics import asr_error_types, cer, percentile, wer

SET_FILE = VALIDATION_DIR / "speech_validation_set.csv"
# To'plamlar: dev — sozlash uchun; heldout — KO'RILMAGAN (sozlashda hech qachon ishlatilmaydi); regression — eski to'plam
# (sintetik benchmark'larda ishlatilgan, shuning uchun endi "ko'rilmagan" emas — regressiya uchun)
SETS = {"heldout": VALIDATION_DIR / "human_heldout_v2.csv", "dev": VALIDATION_DIR / "human_dev.csv", "regression": SET_FILE}
GROUPS = ("uz_latn", "uz_cyrl", "ru", "en", "mixed", "silence")


def set_path(name: str | None) -> Path:
    return SETS.get(name or "regression", SET_FILE)


class ArraySource:
    """Saqlangan yozuvni mikrofon kabi real vaqt tezligida uzatadi (oqimli STT'ni bir xil audio bilan baholash)."""

    def __init__(self, audio: np.ndarray, chunk_ms: int = 64, realtime: bool = True, lead_s: float = 0.5):
        self.pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        self.chunk_ms, self.realtime = chunk_ms, realtime
        self.lead_s = lead_s   # gapdan oldingi jimlik — VAD fon shovqinini nutq emas, jimlikdan kalibrlaydi
        self._stop = threading.Event()

    def start(self, on_chunk) -> None:
        step = 16000 * self.chunk_ms // 1000 * 2

        def run() -> None:
            for _ in range(int(self.lead_s * 1000 / self.chunk_ms)):
                on_chunk(b"\x00" * step)
                if self.realtime:
                    time.sleep(self.chunk_ms / 1000)
            for i in range(0, len(self.pcm), step):
                if self._stop.is_set():
                    return
                on_chunk(self.pcm[i:i + step].ljust(step, b"\x00"))
                if self.realtime:
                    time.sleep(self.chunk_ms / 1000)
            while not self._stop.is_set():   # real mikrofon kabi: gapdan keyin jimlik
                on_chunk(b"\x00" * step)
                time.sleep(self.chunk_ms / 1000 if self.realtime else 0.001)
        threading.Thread(target=run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


class GeminiUnary:
    """Gemini Transcribe (butun yozuv, zaxirasiz) — `Listener` bilan bir xil interfeys."""

    engine = "gemini"

    def __init__(self, cfg):
        from ..speech.recognizer import GeminiTranscriber, make_recognizer

        self._g = GeminiTranscriber(cfg.gemini_api_key, cfg.gemini_stt_model, 60)
        self._vocab = make_recognizer(cfg, None).vocabulary
        self.model_name = cfg.gemini_stt_model

    def warmup(self) -> None:
        pass

    def transcribe(self, audio, language=None, prior=None):
        from ..lang import detect_text_language
        from ..speech.stt import Transcript

        text = self._vocab.correct(self._g.transcribe(audio, language, self._vocab))
        g = detect_text_language(text, prior or "uz") if text else None
        return Transcript(text, g.lang if g else (prior or "uz"), float(g.confidence) if g else 0.0, True,
                          detected_raw="gemini")


class GeminiStream:
    """Oqimli Gemini Live Transcription — yozuv real vaqtda uzatiladi; holat (final/local) yoziladi."""

    engine = "gemini-live"

    def __init__(self, cfg):
        from ..speech.recognizer import make_recognizer

        self.cfg = cfg
        self.model_name = cfg.gemini_stt_live_model
        self._terms = make_recognizer(cfg, None).vocabulary.terms
        self.last_status = ""

    def warmup(self) -> None:
        pass

    def transcribe(self, audio, language=None, prior=None):
        from ..lang import detect_text_language
        from ..speech.stream import StreamingTranscriber
        from ..speech.stt import Transcript

        st = StreamingTranscriber(self.cfg.gemini_api_key, self.model_name, vocabulary=self._terms,
                                  source_factory=lambda: ArraySource(audio))
        r = st.run(threading.Event())
        self.last_status = f"{r.finalized_by}:{r.reason or r.error[:120]}"
        g = detect_text_language(r.text, prior or "uz") if r.text else None
        return Transcript(r.text, g.lang if g else (prior or "uz"), float(g.confidence) if g else 0.0, True,
                          detected_raw=self.last_status)


def make_provider(name: str, cfg, model: str | None = None, engine: str = "auto"):
    if name == "gemini":
        return GeminiUnary(cfg)
    if name == "gemini-live":
        return GeminiStream(cfg)
    from ..speech.stt import Listener

    return Listener(model or cfg.whisper_model, engine)


CONSENT = ("Yozuvlar faqat shu kompyuterda (backend/validation/results/…/audio) saqlanadi va faqat XADICHA AI'ni\n"
           "baholash uchun ishlatiladi. Gemini provayderi bilan baholansa, audio Google'ga yuboriladi.\n"
           "Ovozingiz yozilishiga rozimisiz? (ha / yo'q): ")


def ask_consent(answer: str | None = None) -> bool:
    a = (answer if answer is not None else input(CONSENT)).strip().lower()
    return a in ("ha", "xa", "yes", "y", "да", "ҳа")


def load_set(path: Path = SET_FILE) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group_of(row: dict[str, str]) -> str:
    if row["kind"] in ("silence", "mixed"):
        return row["kind"]
    return "uz_" + row["script"] if row["lang"] == "uz" else row["lang"]


def score_item(row: dict[str, str], hyp: str, asr_lang: str, final_lang: str, selected: str) -> dict[str, Any]:
    """Bitta yozuvni baholash (sof funksiya — testlanadi)."""
    from ..speech_eval import entity_ok, predict

    out: dict[str, Any] = {"id": row["id"], "group": group_of(row), "reference": row["text"], "hypothesis": hyp,
                           "asr_lang": asr_lang, "final_lang": final_lang}
    if row["kind"] == "silence":
        out.update(false_transcription=bool(hyp.strip()))
        return out
    t0 = time.perf_counter()
    p = predict(hyp, selected) if hyp.strip() else {"lang": final_lang, "intent": "", "entity": ""}
    out["intent_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    errs = asr_error_types(row["text"], hyp)
    lid_ok = final_lang == row["lang"]
    intent_ok = p["intent"] == row["intent"]
    ent_ok = intent_ok and entity_ok(row["entity"], p["entity"])
    out.update(
        wer=round(wer(row["text"], hyp), 4), cer=round(cer(row["text"], hyp), 4),
        lid_ok=lid_ok, intent_ok=intent_ok, entity_ok=ent_ok,
        expected=[row["lang"], row["intent"], row["entity"]], got=[final_lang, p["intent"], p["entity"]],
        errors={
            **{k: v for k, v in errs.items() if v},
            **({"language_confusion": f"{row['lang']}→{final_lang}"} if not lid_ok else {}),
            **({"app_name": f"{row['entity']}→{p['entity'] or '∅'}"} if row["intent"] == "open_app" and not ent_ok else {}),
            **({"empty_transcript": True} if not hyp.strip() else {}),
        },
    )
    return out


def _mean(xs: list[float]) -> float | None:
    return round(statistics.mean(xs), 4) if xs else None


def _pct(rs: list[dict[str, Any]], k: str) -> float | None:
    vals = [r[k] for r in rs if k in r]
    return round(100 * sum(1 for v in vals if v) / len(vals), 1) if vals else None


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    def block(rs: list[dict[str, Any]]) -> dict[str, Any]:
        cmd = [r for r in rs if r["group"] != "silence" and not r.get("provider_error")]
        sil = [r for r in rs if r["group"] == "silence" and not r.get("provider_error")]
        asr = [r["asr_ms"] for r in rs if r.get("asr_ms") is not None]
        eos = [r["eos_ms"] for r in rs if r.get("eos_ms") is not None]
        counts: dict[str, int] = {}
        for r in cmd:
            for k in (r.get("errors") or {}):
                counts[k] = counts.get(k, 0) + 1
        return {
            "n": len(rs), "n_commands": len(cmd),
            "wer_mean": _mean([r["wer"] for r in cmd if "wer" in r]),
            "cer_mean": _mean([r["cer"] for r in cmd if "cer" in r]),
            "lid_accuracy": _pct(cmd, "lid_ok"), "intent_accuracy": _pct(cmd, "intent_ok"),
            "entity_accuracy": _pct(cmd, "entity_ok"),
            "asr_ms_median": round(statistics.median(asr)) if asr else None,
            "asr_ms_p90": round(percentile(asr, 90)) if asr else None,
            "eos_ms_median": round(statistics.median(eos)) if eos else None,
            "eos_ms_p90": round(percentile(eos, 90)) if eos else None,
            "silence_trials": len(sil),
            "silence_false_transcriptions": sum(1 for r in sil if r.get("false_transcription")),
            "provider_errors": sum(1 for r in rs if r.get("provider_error")),
            "error_counts": counts,
        }

    out = {"overall": block(items), "by_group": {}}
    for g in GROUPS:
        rs = [r for r in items if r["group"] == g]
        if rs:
            out["by_group"][g] = block(rs)
    return out


def write_wav(path: Path, audio: np.ndarray, rate: int = 16000) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def vad_replay(audio: np.ndarray) -> str:
    """Saqlangan yozuvni ilovadagi VAD orqali o'tkazish (oflayn): "silence" — nutq sezildi va tugadi,
    "no_speech" — nutq sezilmadi, "max_seconds" — yozuv tugaguncha gap davom etdi."""
    from ..speech.stt import BLOCK, Endpointer

    ep = Endpointer()
    for i in range(0, len(audio) - BLOCK + 1, BLOCK):
        c = audio[i:i + BLOCK]
        if ep.feed(float(np.sqrt(np.mean(c * c))), BLOCK / 16000):
            break
    return ep.reason or ("max_seconds" if ep.heard else "no_speech")


def _transcribe_and_score(li, row, audio, selected: str, no_speech: bool = False) -> dict[str, Any]:
    from ..lang import refine_asr_language
    from ..speech.stt import is_prompt_echo

    t0 = time.perf_counter()
    tr = li.transcribe(audio, None, prior=selected)
    asr_ms = round((time.perf_counter() - t0) * 1000)
    filtered = bool(no_speech and tr.text and is_prompt_echo(tr.text, tr.asr_confidence))
    if filtered:   # ilovadagi kabi: VAD nutq sezmagan + Whisper yordamchi so'rovni qaytargan — nutq emas
        tr.text = ""
    t1 = time.perf_counter()
    final = refine_asr_language(tr.text, tr.language, tr.probability or None, selected) if tr.text else tr.language
    lang_ms = round((time.perf_counter() - t1) * 1000, 1)
    rec = score_item(row, tr.text, tr.language, final, selected)
    rec.update(asr_ms=asr_ms, lang_ms=lang_ms, asr_confidence=tr.asr_confidence, whisper_raw_lang=tr.detected_raw,
               audio_s=round(len(audio) / 16000, 2), engine=li.engine, model=li.model_name)
    if getattr(li, "engine", "") == "gemini-live":
        rec["transcript_status"] = getattr(li, "last_status", "")
    if filtered:
        rec["asr_filter"] = "prompt_echo_without_speech"
    return rec


def _retry_after(e: BaseException, default: float) -> float:
    m = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", f"{e} {e.__cause__ or ''}")
    return min(90.0, float(m.group(1)) + 1.0) if m else default


def score_safely(li, row, audio, selected: str, no_speech: bool = False, retries: int = 3, wait_s: float = 25.0,
                 sleep=time.sleep) -> dict[str, Any]:
    """Bitta yozuv xatosi (kvota 429, tarmoq) butun baholashni to'xtatmasin: kvotada kutib qayta urinadi, boshqa
    xatoda yozuv "provider_error" bilan belgilanadi va WER/aniqlik hisobiga KIRMAYDI (alohida sanaladi)."""
    from ..providers.base import ProviderError
    from ..redaction import redact

    last: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return _transcribe_and_score(li, row, audio, selected, no_speech)
        except ProviderError as e:
            last = e
            if e.kind != "quota" or attempt == retries:
                break
            sleep(_retry_after(e, wait_s))
        except Exception as e:  # noqa: BLE001
            last = e
            break
    return {"id": row["id"], "group": group_of(row), "reference": row["text"], "hypothesis": "",
            "provider_error": redact(f"{type(last).__name__}: {last}")[:200], "asr_ms": None,
            "engine": getattr(li, "engine", ""), "model": getattr(li, "model_name", "")}


def write_csv(path: Path, items: list[dict[str, Any]]) -> Path:
    """Mashina o'qiydigan natija (har yozuv — bitta qator)."""
    cols = ["provider", "id", "group", "reference", "hypothesis", "wer", "cer", "lid_ok", "intent_ok", "entity_ok",
            "asr_ms", "final_lang", "transcript_status", "vad_replay", "asr_filter", "provider_error"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    return path


def _record(li, max_seconds: float):
    from ..speech.stt import Endpointer

    ep, stop = Endpointer(), threading.Event()
    print("     🎙 GAPIRING", flush=True)
    t0 = time.perf_counter()
    audio = li.record_until(stop, max_seconds=max_seconds, endpointer=ep)
    return audio, ep, round((time.perf_counter() - t0) * 1000)


def mic_check(li, ask=input) -> dict[str, Any] | None:
    """Sessiyadan oldin mikrofon tekshiruvi: nutq sezilyaptimi va daraja yetarlimi (2026-11-26 dagi sessiyada
    VAD nutqni umuman sezmagan, natija yaroqsiz bo'lgan). Qaytaradi: o'lchov yoki None (foydalanuvchi chiqdi)."""
    while True:
        ask("Mikrofon tekshiruvi: Enter bosing va «Salom, men tayyorman» deng...")
        audio, ep, _ = _record(li, 8)
        peak = round(float(np.abs(audio).max()) if audio.size else 0.0, 3)
        res = {"speech_detected": ep.reason == "silence", "peak": peak, "speech_s": round(ep.speech_total, 2),
               "noise_floor": round(ep.floor or 0.0, 5)}
        if res["speech_detected"] and peak >= 0.05:
            print(f"     ✓ Mikrofon yaxshi (daraja {peak:.2f}, nutq {res['speech_s']} s).\n")
            return res
        why = "nutq sezilmadi" if not res["speech_detected"] else "ovoz juda past"
        print(f"     ⚠ {why} (eng baland daraja {peak:.2f}). Mikrofonga yaqinroq gapiring yoki Tizim sozlamalari → "
              "Ovoz → Kirish darajasini oshiring.")
        a = ask("     Enter — qayta tekshirish, d — shunday davom etish, q — chiqish: ").strip().lower()
        if a == "q":
            return None
        if a == "d":
            return res


def record_session(args, cfg) -> int:
    from ..speech.stt import Listener

    set_file = set_path(getattr(args, "set", None))
    rows = load_set(set_file)
    only = set(filter(None, (args.only or "").split(",")))
    rows = [r for r in rows if not only or group_of(r) in only]
    if args.limit:
        rows = rows[: args.limit]
    if not ask_consent(getattr(args, "consent", None)):
        print("Rozilik berilmadi — hech narsa yozilmadi.")
        return 3
    run_id = stamp()
    audio_dir = RESULTS_DIR / f"speech-{run_id}" / "audio"
    li = Listener(cfg.whisper_model, cfg.stt_engine)
    print(f"ASR: {li.engine} · {cfg.whisper_model}. Model yuklanmoqda (birinchi marta bir necha daqiqa olishi mumkin)...")
    t0 = time.perf_counter()
    li.warmup()
    load_s = round(time.perf_counter() - t0, 2)
    print(f"Yuklandi: {load_s} s.\n")
    print("Har bir qatorda: Enter bosing → «GAPIRING» chiqqach ko'rsatilgan matnni oddiy ovozda o'qing → jim turing.\n"
          "Faqat ko'rsatilgan matnni o'qing («Xadicha» deyish shart emas). Yozish o'zi to'xtaydi.\n"
          "'JIMLIK' qatorlarida hech narsa demang (fon shovqini sinovi). Chiqish: Ctrl+C (yozilganlar saqlanadi).\n")
    mic = mic_check(li)
    if mic is None:
        return 4
    audio_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    meta = {"selected_language_prior": args.selected, "engine": li.engine, "model": cfg.whisper_model,
            "model_load_s": load_s, "set_file": str(set_file.name), "audio_dir": str(audio_dir),
            "kind": "real microphone recordings (user)", "real": True, "consent": True,
            "speaker": getattr(args, "speaker", "") or "anon", "environment": getattr(args, "env", "") or "quiet",
            "speed": getattr(args, "speed", "") or "normal", "microphone": cfg.microphone or "default",
            "mic_check": mic, "vad": "time-based noise tracking (2026-11-27)"}

    def save() -> Path:
        return save_result("speech", {**meta, "summary": summarize(items), "items": items}, run_id)

    try:
        for i, row in enumerate(rows, 1):
            label = "JIMLIK — hech narsa demang" if row["kind"] == "silence" else row["text"]
            input(f"[{i}/{len(rows)}] {group_of(row):8} «{label}»  — Enter...")
            while True:
                audio, ep, cap_ms = _record(li, 8 if row["kind"] == "silence" else 15)
                if row["kind"] == "silence" or ep.reason == "silence":
                    break
                peak = float(np.abs(audio).max()) if audio.size else 0.0
                a = input(f"     ⚠ Nutq sezilmadi ({ep.reason or 'max_seconds'}, eng baland daraja {peak:.2f}). "
                          "Enter — qayta yozish, s — shunday saqlash: ").strip().lower()
                if a == "s":
                    break
            write_wav(audio_dir / f"{row['id']}.wav", audio)
            rec = _transcribe_and_score(li, row, audio, args.selected, no_speech=ep.reason == "no_speech")
            rec.update(capture_ms=cap_ms, vad_reason=ep.reason or "max_seconds",
                       eos_ms=round(ep.endpoint_delay_s * 1000) if ep.reason == "silence" else None,
                       speech_s=round(ep.speech_total, 2), noise_floor=round(ep.floor or 0, 5),
                       peak=round(float(np.abs(audio).max()) if audio.size else 0.0, 3))
            if row["kind"] != "silence" and ep.reason != "silence":
                rec.setdefault("errors", {})["vad"] = ep.reason or "max_seconds"
            items.append(rec)
            mark = "✓" if rec.get("intent_ok") or (row["kind"] == "silence" and not rec.get("false_transcription")) else "✗"
            print(f"     {mark} «{rec['hypothesis']}»  WER={rec.get('wer', '-')}  til={rec['final_lang']}  "
                  f"ASR={rec['asr_ms']} ms  EOS={rec['eos_ms']} ms")
            save()
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
    path = save()
    print(json.dumps(summarize(items)["overall"], ensure_ascii=False, indent=2))
    print(f"\nSaqlandi: {path}\nAudio: {audio_dir}")
    return 0


def rescore(args, cfg) -> int:
    """Saqlangan haqiqiy yozuvlarni boshqa model/dvigatel bilan qayta baholash (ASR modellarini solishtirish)."""
    from ..speech.stt import Listener
    from ..speech_eval import read_wav

    run_dir = Path(args.rescore)
    audio_dir = run_dir / "audio" if (run_dir / "audio").exists() else run_dir
    rows = {r["id"]: r for name in SETS for r in load_set(SETS[name]) if SETS[name].exists()}
    files = sorted(p for p in audio_dir.glob("*.wav") if p.stem in rows)
    if not files:
        print(f"{audio_dir} da yozuv topilmadi.")
        return 2
    comparisons = {}
    providers = [p.strip() for p in (getattr(args, "providers", "") or "whisper").split(",") if p.strip()]
    all_items: list[dict[str, Any]] = []
    vad = {f.stem: vad_replay(read_wav(f)) for f in files}
    for name in [p for p in providers if p != "whisper"]:
        li = make_provider(name, cfg)
        items = []
        for f in files:
            rec = score_safely(li, rows[f.stem], read_wav(f), args.selected, no_speech=vad[f.stem] == "no_speech")
            rec.update(provider=name, vad_replay=vad[f.stem])
            items.append(rec)
        comparisons[name] = {"summary": summarize(items), "items": items}
        all_items += items
        print(name, json.dumps(summarize(items)["overall"], ensure_ascii=False))
    for engine in ((args.engines or "auto").split(",") if "whisper" in providers else []):
        for model in (args.models or cfg.whisper_model).split(","):
            li = Listener(model, engine)
            t0 = time.perf_counter()
            li.warmup()
            load_s = round(time.perf_counter() - t0, 2)
            items = []
            for f in files:
                audio = read_wav(f)
                rec = score_safely(li, rows[f.stem], audio, args.selected, no_speech=vad[f.stem] == "no_speech")
                rec.update(provider=f"whisper:{li.engine}:{model}", vad_replay=vad[f.stem])
                items.append(rec)
            comparisons[f"{li.engine}:{model}"] = {"model_load_s": load_s, "summary": summarize(items), "items": items}
            all_items += items
            print(f"{li.engine}:{model}", json.dumps(summarize(items)["overall"], ensure_ascii=False))
    path = save_result("speech_rescore", {"source_audio": str(audio_dir), "selected_language_prior": args.selected,
                                          "real": True, "kind": "re-transcription of real recordings",
                                          "comparisons": comparisons})
    print(f"Saqlandi: {path}")
    print(f"CSV: {write_csv(Path(str(path)).with_suffix('.csv'), all_items)}")
    return 0


def text_only(args) -> int:
    """Tushunish qatlamini (til, niyat, obyekt) ko'rilmagan to'plamning MATNIDA baholash — ASR'siz.
    Bu real nutq natijasi emas; faqat ASR xatosiz holatdagi yuqori chegara."""
    from ..lang import detect_text_language

    items = []
    for row in load_set():
        if row["kind"] == "silence":
            continue
        lang = detect_text_language(row["text"], args.selected).lang
        items.append(score_item(row, row["text"], lang, lang, args.selected))
    summary = summarize(items)
    path = save_result("speech_text", {"kind": "text-only on held-out set (no ASR, no audio)", "real": False,
                                       "selected_language_prior": args.selected, "summary": summary, "items": items})
    print(json.dumps({k: summary["overall"][k] for k in ("n_commands", "lid_accuracy", "intent_accuracy",
                                                          "entity_accuracy")}, ensure_ascii=False))
    for g, b in summary["by_group"].items():
        print(f"  {g:8} n={b['n_commands']:2}  til={b['lid_accuracy']}  niyat={b['intent_accuracy']}  obyekt={b['entity_accuracy']}")
    errs = [r for r in items if not (r["lid_ok"] and r["intent_ok"] and r["entity_ok"])]
    for r in errs:
        print(f"  ✗ {r['id']}: «{r['reference']}»  kutilgan={r['expected']}  olindi={r['got']}")
    print(f"Saqlandi: {path}")
    return 0


def main(args) -> int:
    from ..config import load_config

    if args.text_only:
        return text_only(args)
    cfg = load_config()
    if args.rescore:
        return rescore(args, cfg)
    if not is_macos():
        print("Mikrofon sinovi faqat Mac'da (real qurilmada) o'tkaziladi.")
        return 2
    return record_session(args, cfg)
