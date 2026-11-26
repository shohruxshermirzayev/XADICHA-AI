"""HAQIQIY Gemini API smoke testi (internet va backend/.env dagi GEMINI_API_KEY kerak).

  cd backend && source .venv/bin/activate
  python scripts/gemini_smoke.py                 # barcha qadamlar
  python scripts/gemini_smoke.py --skip-search   # Google Search grounding'siz (bepul tarifda mavjud emas)
  python scripts/gemini_smoke.py --json out.json # natijani faylga yozish

Kalit hech qachon chiqarilmaydi: faqat "o'rnatilgan / yo'q". Har bir qadam haqiqiy so'rov; natija — o'lchangan qiymat.
Bu skript avtomatik testlar (pytest) tarkibiga kirmaydi — ular simulyatsiya.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xadicha.config import load_config  # noqa: E402
from xadicha.providers.base import ProviderError  # noqa: E402
from xadicha.redaction import redact  # noqa: E402

RESULTS: list[dict] = []


def step(name: str):
    def deco(fn):
        def run(*a, **k):
            t0 = time.perf_counter()
            try:
                info = fn(*a, **k) or {}
                ok = info.pop("_ok", True)
            except ProviderError as e:
                ok, info = False, {"error": redact(str(e)), "kind": getattr(e, "kind", "error")}
            except Exception as e:  # noqa: BLE001
                ok, info = False, {"error": redact(f"{e.__class__.__name__}: {e}")[:300]}
            ms = int((time.perf_counter() - t0) * 1000)
            RESULTS.append({"step": name, "ok": ok, "ms": ms, **info})
            mark = "✅" if ok else "❌"
            print(f"{mark} {name}  ({ms} ms)")
            for k, v in info.items():
                print(f"     {k}: {v}")
            return ok
        return run
    return deco


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-search", action="store_true")
    ap.add_argument("--skip-fallback", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    cfg = load_config()
    print(f"provayder={cfg.provider}  model={cfg.gemini_model}  qidiruv={cfg.search_mode}  "
          f"zaxira={cfg.fallback} ({cfg.ollama_model})  GEMINI_API_KEY={'o`rnatilgan' if cfg.gemini_api_key else 'YO`Q'}")
    if not cfg.gemini_api_key:
        print("GEMINI_API_KEY yo'q — haqiqiy sinov bajarilmadi.")
        return 2

    from xadicha.providers.gemini_provider import GeminiProvider

    g = GeminiProvider(cfg.gemini_api_key, cfg.gemini_model, cfg.gemini_timeout_s, cfg.gemini_thinking,
                       fallback_models=cfg.gemini_fallback_models)
    print(f"Gemini model zanjiri: {' → '.join(g.models)}")

    @step("1. Kalit va model mavjudligi (models.get)")
    def s1():
        ok, detail = g.health()
        return {"_ok": ok, "detail": detail, "model": g.model}

    @step("2. Matn → JSON javob")
    def s2():
        raw = g.complete('Reply with ONE JSON object {"reply": "..."} in Uzbek (Latin script).',
                         "Salom! O'zingni bir gapda tanishtir.", None)
        reply = json.loads(raw).get("reply", "")
        return {"_ok": bool(reply), "model_used": g.model, "reply": reply[:160]}

    @step("3. Rasm tushunish (sintetik rasm: qizil kvadrat + matn)")
    def s3():
        from PIL import Image, ImageDraw

        from xadicha.vision.screen import Screenshot

        img = Image.new("RGB", (320, 160), "white")
        d = ImageDraw.Draw(img)
        d.rectangle([20, 30, 120, 130], fill=(220, 30, 30))
        d.text((150, 70), "XADICHA 42", fill="black")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        shot = Screenshot(base64.b64encode(buf.getvalue()).decode(), 320, 160, 1.0, "image/png")
        raw = g.complete('Look at the image. Reply with ONE JSON object {"shape_color": "...", "text": "..."}.',
                         "What color is the square and what text is written?", shot)
        data = json.loads(raw)
        color, text = str(data.get("shape_color", "")).lower(), str(data.get("text", ""))
        return {"_ok": "red" in color and "42" in text, "model_used": g.model, "answer": data}

    @step("4. Agent qarori formati (decide → Decision, uz)")
    def s4():
        d = g.decide("Safari ni och", [], None, "uz")
        a = d.action.type if d.action else None
        return {"_ok": a in ("open_app", "open_url") or d.done, "model_used": g.model, "action": a,
                "app": d.action.app if d.action else None, "risk": d.risk.value}

    @step("5. Aralash til (ru+uz) → agent qarori")
    def s5():
        d = g.decide("Рабочий столдаги Excel файлни оч", [], None, "uz")
        a = d.action.type if d.action else None
        return {"_ok": d.action is not None or bool(d.final_message), "model_used": g.model, "action": a,
                "detail": (d.action.describe() if d.action else d.final_message)[:120]}

    steps = [s1, s2, s3, s4, s5]

    if not args.skip_search:
        @step("6. Google Search grounding (dolzarb savol)")
        def s6():
            a = g.grounded_answer("Gemini Live API haqida eng so'nggi rasmiy yangiliklar qanday?", "uz", force=True)
            return {"_ok": a.grounded and bool(a.sources), "model_used": a.model, "grounded": a.grounded, "sources": len(a.sources),
                    "domains": [s["title"] for s in a.sources[:5]], "queries": a.queries[:3],
                    "search_suggestions_html": bool(a.search_entry_point), "answer": a.text[:200]}
        steps.append(s6)

    if not args.skip_fallback:
        from xadicha.providers.fallback import FallbackProvider
        from xadicha.providers.ollama_provider import OllamaProvider

        @step("7. Fallback: noto'g'ri kalit → Ollama")
        def s7():
            bad = GeminiProvider("invalid-key-for-fallback-test", cfg.gemini_model, 15, cfg.gemini_thinking)
            fp = FallbackProvider(bad, OllamaProvider(cfg.ollama_url, cfg.ollama_model))
            raw = fp.complete('Reply with ONE JSON object {"reply": "..."} in English.', "Say hello in three words.", None)
            info = fp.info()
            return {"_ok": info["active"] == "ollama" and info["last_error_kind"] == "auth",
                    "active": info["active"], "gemini_error_kind": info["last_error_kind"],
                    "gemini_error": info["last_error"][:120], "ollama_reply": raw[:120]}

        @step("8. Fallback: tarmoq uzilgan (yopiq port) → Ollama")
        def s8():
            from google import genai
            from google.genai import types

            dead = genai.Client(api_key="invalid-key-for-fallback-test", http_options=types.HttpOptions(
                base_url="http://127.0.0.1:9/", timeout=5000, retry_options=types.HttpRetryOptions(attempts=1)))
            offline = GeminiProvider("x" * 12, cfg.gemini_model, 5, cfg.gemini_thinking, client=dead)
            fp = FallbackProvider(offline, OllamaProvider(cfg.ollama_url, cfg.ollama_model))
            fp.complete('Reply with ONE JSON object {"reply": "..."}.', "Say ok.", None)
            info = fp.info()
            return {"_ok": info["active"] == "ollama" and info["last_error_kind"] in ("network", "timeout"),
                    "active": info["active"], "gemini_error_kind": info["last_error_kind"]}
        steps += [s7, s8]

    passed = sum(1 for s in steps if s())
    print(f"\n{passed}/{len(steps)} qadam muvaffaqiyatli (HAQIQIY API).")
    if args.json:
        Path(args.json).write_text(json.dumps({"model": cfg.gemini_model, "results": RESULTS}, ensure_ascii=False,
                                              indent=2), encoding="utf-8")
    return 0 if passed == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
