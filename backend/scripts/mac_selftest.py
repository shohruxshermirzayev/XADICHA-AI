"""XADICHA AI — macOS real qurilma tekshiruvi (qo'lda, har bir qadam ruxsat bilan).

  cd backend && source .venv/bin/activate
  python scripts/mac_selftest.py              # barcha qadamlar, har biridan oldin so'raydi
  python scripts/mac_selftest.py --only mic,tts,screenshot

Nima qilmaydi: hech narsani o'chirmaydi, xabar yubormaydi, ekran suratini saqlamaydi (--save-screenshot bo'lmasa).
Natija: backend/data/selftest-<vaqt>.json — OS, qurilma, provayder, sozlamalar, har qadam natijasi va xatolar.
Batafsil protokol: docs/MACOS_TEST_PROTOCOL.md
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xadicha.config import load_config  # noqa: E402
from xadicha.metrics import cer, wer  # noqa: E402

REFERENCE = {
    "uz": "Safari ni och va kun uz saytiga kir",
    "ru": "Открой Safari и зайди на сайт kun uz",
    "en": "Open Safari and go to the kun uz website",
}
TTS_TEXT = {"uz": "Salom, men Xadicha.", "ru": "Здравствуйте, я Хадича.", "en": "Hello, I am Xadicha."}


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def environment(cfg) -> dict:
    return {
        "os": f"macOS {platform.mac_ver()[0]}" if platform.system() == "Darwin" else platform.platform(),
        "arch": platform.machine(),
        "hardware_model": sh(["sysctl", "-n", "hw.model"]),
        "cpu": sh(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "python": platform.python_version(),
        "provider": cfg.provider,
        "model": {"claude": cfg.claude_model, "ollama": cfg.ollama_model}.get(cfg.provider, "rules"),
        "whisper_model": cfg.whisper_model, "stt_engine": cfg.stt_engine, "tts_engine": cfg.tts_engine,
        "confirm_risk": cfg.confirm_risk, "workspace": str(cfg.workspace),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def ask(q: str, auto: bool) -> bool:
    if auto:
        return True
    return input(f"\n▶ {q} [y/N]: ").strip().lower() in {"y", "yes", "h", "ha"}


class Runner:
    def __init__(self, auto: bool):
        self.auto, self.results = auto, []

    def step(self, name: str, question: str, fn):
        rec = {"name": name, "status": "skipped", "observed": None, "error": None, "duration_ms": 0}
        if ask(question, self.auto):
            t0 = time.time()
            try:
                obs = fn()
                rec["observed"] = obs
                ok = obs.pop("_ok", True) if isinstance(obs, dict) else True
                rec["status"] = "passed" if ok else "failed"
            except Exception as e:  # noqa: BLE001
                rec["status"], rec["error"] = "failed", f"{e.__class__.__name__}: {e}"
                traceback.print_exc()
            rec["duration_ms"] = int((time.time() - t0) * 1000)
        mark = {"passed": "✅", "failed": "❌", "skipped": "⏭"}[rec["status"]]
        print(f"  {mark} {name}: {rec['status']} {rec['error'] or rec['observed'] or ''}")
        self.results.append(rec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="vergul bilan qadam nomlari")
    ap.add_argument("--yes", action="store_true", help="har qadamda so'ramaslik (faqat o'zingiz kuzatib tursangiz)")
    ap.add_argument("--save-screenshot", action="store_true")
    args = ap.parse_args()
    only = set(filter(None, args.only.split(",")))

    if platform.system() != "Darwin":
        print("Bu skript faqat macOS uchun.")
        return 2
    cfg = load_config()
    from xadicha.adapters.macos import MacOSAdapter
    from xadicha.models import Action

    adapter = MacOSAdapter()
    r = Runner(args.yes)
    env = environment(cfg)
    print("XADICHA AI — macOS tekshiruvi\n" + json.dumps(env, ensure_ascii=False, indent=2))

    def want(n: str) -> bool:
        return not only or n in only

    if want("permissions"):
        r.step("permissions", "Ruxsatlarni tekshiraymi (Accessibility)?", lambda: adapter.permissions())

    if want("mic"):
        def mic():
            import sounddevice as sd

            dev = sd.query_devices(kind="input")
            return {"device": dev.get("name"), "default_samplerate": dev.get("default_samplerate")}
        r.step("mic", "Mikrofon qurilmasini aniqlaymi (yozmasdan)?", mic)

    if want("speech"):
        def speech():
            from xadicha.speech.stt import Listener

            li = Listener(cfg.whisper_model, cfg.stt_engine)
            out = {"engine": li.engine, "results": {}}
            for lang, ref in REFERENCE.items():
                input(f"   [{lang}] Enter bosing va 5 soniya ichida o'qing: «{ref}»")
                stop = threading.Event()
                threading.Timer(5.0, stop.set).start()
                audio = li.record_until(stop)
                t0 = time.time()
                tr = li.transcribe(audio, lang)
                out["results"][lang] = {"reference": ref, "hypothesis": tr.text, "wer": round(wer(ref, tr.text), 3),
                                        "cer": round(cer(ref, tr.text), 3), "asr_confidence": tr.asr_confidence,
                                        "transcribe_ms": int((time.time() - t0) * 1000)}
                print(f"      → {tr.text!r}  WER={out['results'][lang]['wer']}")
            return out
        r.step("speech", "Mikrofondan 3 ta jumla yozib (uz/ru/en), matnga aylantiraymi?", speech)

    if want("tts"):
        def tts():
            from xadicha.speech.tts import Speaker

            sp = Speaker(cfg.tts_engine, cfg.tts_rate, {"uz": cfg.voice_uz, "ru": cfg.voice_ru, "en": cfg.voice_en}, True)
            res = {lang: sp.say(text, lang, block=True) for lang, text in TTS_TEXT.items()}
            heard = input("   Uchala tilda ovoz eshitildimi? [y/N]: ").strip().lower() in {"y", "ha", "h"}
            return {"spoken": res, "user_heard_all": heard, "_ok": heard}
        r.step("tts", "Ovozli javobni (uz/ru/en) aytib ko'raymi?", tts)

    shot_holder = {}
    if want("screenshot"):
        def screenshot():
            from xadicha.vision.screen import capture_image, encode

            t0 = time.time()
            img, lw, lh = capture_image(adapter.screen_size())
            shot = encode(img, lw, lh, cfg.screen_max_side)
            shot_holder.update(img=img, size=(lw, lh))
            if args.save_screenshot:
                p = Path(cfg.db_path).parent / f"selftest-screen-{int(time.time())}.png"
                img.save(p)
            return {"pixels": list(img.size), "logical": [lw, lh], "sent_to_model": [shot.width, shot.height],
                    "scale": round(shot.scale, 3), "capture_ms": int((time.time() - t0) * 1000),
                    "_ok": img.size[0] > 0 and img.getbbox() is not None}
        r.step("screenshot", "Ekran suratini olaymi (diskka saqlanmaydi)?", screenshot)

    if want("ocr"):
        def ocr():
            from xadicha.vision.context import make_ocr

            o = make_ocr()
            state, detail = o.availability()
            if state == "unavailable" or "img" not in shot_holder:
                return {"state": state, "detail": detail, "_ok": False}
            boxes = o.recognize(shot_holder["img"], shot_holder["size"])
            return {"state": state, "boxes": len(boxes), "sample": [b.text for b in boxes[:5]], "_ok": bool(boxes)}
        r.step("ocr", "Ekran suratidagi matnni OCR bilan o'qiymi?", ocr)

    if want("ax"):
        def ax():
            from xadicha.vision.context import make_accessibility

            a = make_accessibility()
            state, detail = a.availability()
            els = a.snapshot()
            return {"state": state, "detail": detail, "elements": len(els),
                    "sample": [f"{e.role}:{e.name}" for e in els[:5]], "_ok": bool(els)}
        r.step("ax", "Old plandagi ilovaning accessibility elementlarini o'qiymi?", ax)

    if want("open_app"):
        def open_app():
            res = adapter.execute(Action(type="open_app", app="Calculator"))
            return {"ok": res.ok, "verified": res.verified, "detail": res.detail, "frontmost": adapter.frontmost_app(),
                    "_ok": res.ok and res.verified is True}
        r.step("open_app", "Calculator ilovasini ochaymi (zararsiz)?", open_app)

    if want("folder"):
        def folder():
            p = cfg.workspace.expanduser() / f"xadicha-selftest-{time.strftime('%Y%m%d-%H%M%S')}"
            res = adapter.execute(Action(type="create_folder", path=str(p)))
            return {"path": str(p), "ok": res.ok, "verified": res.verified, "exists": p.is_dir(),
                    "note": "papka o'chirilmaydi — keyin o'zingiz o'chiring", "_ok": p.is_dir()}
        r.step("folder", f"{cfg.workspace} ichida test papkasi yarataymi (o'chirilmaydi)?", folder)

    if want("type"):
        def type_text():
            adapter.execute(Action(type="open_app", app="TextEdit"))
            input("   TextEdit'da yangi BO'SH hujjat oching, matn maydonini bosing, so'ng Enter bosing...")
            text = "XADICHA test 123 — Salom, Салом, ўқғҳ"
            time.sleep(0.5)
            res = adapter.execute(Action(type="type_text", text=text))
            seen = input(f"   Hujjatda «{text}» to'liq ko'rindimi? [y/N]: ").strip().lower() in {"y", "ha", "h"}
            return {"ok": res.ok, "typed": text, "user_confirmed_visible": seen, "_ok": res.ok and seen}
        r.step("type", "TextEdit'dagi bo'sh hujjatga matn yozaymi?", type_text)

    if want("stop"):
        def stop():
            # Xavfsiz sinov: reja faqat kutish qadamlaridan iborat — hech qanday GUI harakati yo'q
            from xadicha.agent import Agent
            from xadicha.models import Mode
            from xadicha.providers.rule_based import RuleBasedProvider

            class WaitPlan(RuleBasedProvider):
                def plan(self, instruction, language):
                    from xadicha.models import Decision, Plan

                    return Plan(steps=[Decision(action=Action(type="wait", seconds=10)) for _ in range(3)])

            agent = Agent(cfg, WaitPlan(), adapter, None)
            threading.Timer(1.0, agent.stop).start()
            t0 = time.time()
            task = agent.run("kut", "uz", Mode.llm_plan)
            el = time.time() - t0
            return {"status": task.status.value, "elapsed_s": round(el, 2), "_ok": task.status.value == "cancelled" and el < 3}
        r.step("stop", "Faol vazifani (faqat kutish qadamlari) 1 soniyadan keyin to'xtatishni sinaymi?", stop)

    out = Path(cfg.db_path).parent / f"selftest-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"environment": env, "results": r.results, "kind": "real-device manual test"},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for x in r.results if x["status"] == "passed")
    failed = sum(1 for x in r.results if x["status"] == "failed")
    print(f"\nNatija: {passed} o'tdi, {failed} yiqildi, {len(r.results) - passed - failed} o'tkazib yuborildi → {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
