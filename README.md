# XADICHA AI

O'zbek, rus va ingliz tillaridagi tabiiy nutq hamda vizual kontekst asosida kompyuter interfeysini boshqaruvchi multimodal AI agent (magistrlik dissertatsiyasi loyihasi).

```
XADICHA AI/
├── backend/   ← Python agent: nutq, ekran, model, boshqaruv, xavfsizlik, FastAPI
└── src/       ← Next.js interfeys: yordamchi, dashboard, ekran tahlili, tarix, tadqiqot, sozlamalar
```

## Ishga tushirish (ikki Terminal tab)

**1-tab — backend (agent):**
```bash
cd ~/MAGISTRATURA/"XADICHA AI"/backend
source .venv/bin/activate
python -m xadicha serve
```

**2-tab — interfeys:**
```bash
cd ~/MAGISTRATURA/"XADICHA AI"
npm run dev
```

Keyin brauzerda http://localhost:3000 ni oching.

Faqat terminalda ishlatish: `python -m xadicha` (matn) yoki `python -m xadicha --voice --lang uz` (ovoz).
Batafsil: [backend/README.md](backend/README.md).

## Stek

Backend: Python 3.12, FastAPI, Pydantic, SQLite, faster-whisper, Ollama (Qwen 3.5) yoki Claude API.
Interfeys: Next.js 16, Tailwind CSS 4, Motion, lucide-react; shadcn/ui, Magic UI va React Bits registrlari `components.json` da ulangan.

## Asosiy imkoniyatlar (hozirgi kod)

- **A / B / C rejimlari** — tadqiqot uchun solishtiriladi (A: qoida, B: LLM reja, C: ekran + tekshiruv + tiklanish).
- **Ovoz** — mikrofonni faqat backend yozadi; Whisper (MLX / faster-whisper). Nutq ishonchi va buyruq aniqligi alohida
  baholanadi; noaniq buyruqda eshitilgan matn ko'rsatiladi va foydalanuvchi tanlaydi (jimgina almashtirish yo'q).
- **Yagona holat** — sarlavha, yordamchi, vazifa paneli va dashboard bir manbadan (`phase`, `seq`).
- **Xavfsizlik** — Host/Origin/sessiya kaliti, xavf tasnifi, tasdiq, taqiqlangan yo'llar, log redaksiyasi ([docs/SECURITY.md](docs/SECURITY.md)).
- **Ekran** — surat + vision model; macOS'da ixtiyoriy OCR (Apple Vision) va accessibility daraxti (AXUIElement) — sinalmagan MVP.
- **3 tilli interfeys** — o'zbek, rus, ingliz; o'zbek kirill buyruqlari.
- **Benchmark** — 32 vazifa × 4 variant, xom loglar va metrikalar ([docs/RESEARCH_METHODOLOGY.md](docs/RESEARCH_METHODOLOGY.md)).

macOS uchun ixtiyoriy OCR/accessibility: `pip install -r backend/requirements-macos-optional.txt`.

## Tekshirish (testlar)

```bash
cd backend && source .venv/bin/activate && python -m pytest -q   # backend: 167 ta test (simulyatsiya)
cd .. && npm test              # interfeys mantiqi: holat modeli, hodisalar, tarjimalar (22 ta test)
npm run lint                   # ESLint
npm run typecheck              # TypeScript
npm run build                  # production build
```

Real Mac'da tekshirish: `python backend/scripts/mac_selftest.py` — [docs/MACOS_TEST_PROTOCOL.md](docs/MACOS_TEST_PROTOCOL.md).
Benchmark: `cd backend && python -m xadicha.benchmark --dry-run` (harness tekshiruvi, natija emas).

Testlar simulyatsiya qilingan model va **dry-run** adapter bilan ishlaydi — ular real Mac yoki Windows'da
harakat bajarilishini isbotlamaydi. Batafsil: [docs/TESTING.md](docs/TESTING.md).

## Holati (halollik bilan)

| Qism | Holat |
|---|---|
| Agent sikli (A/B/C), xavfsizlik siyosati, tasdiq, favqulodda to'xtatish | ✅ avtomatik testlar (simulyatsiya) |
| Yagona holat, qayta ulanish, aniqlashtirish, mahalliy API himoyasi | ✅ avtomatik testlar (simulyatsiya) |
| Interfeys: tasdiq dialogi, 3 til, kirill kiritish, qayta ulanish | ✅ headless Chrome'da (dry-run backend bilan) |
| Ekran tahlili | ⚠️ surat + vision model; real Mac'da sinalmagan |
| OCR (Apple Vision), accessibility daraxti (AXUIElement) | ⚠️ ixtiyoriy MVP, real Mac'da sinalmagan |
| macOS adapteri | ⚠️ real Mac'da avtomatik sinalmagan |
| Windows adapteri | ⚠️ Windows qurilmasida umuman sinalmagan |
| Mikrofon, STT/TTS | ⚠️ real qurilmada avtomatik sinalmagan; o'zbekcha WER o'lchanmagan |
| Claude / Ollama provayderlari | ⚠️ real model bilan avtomatik sinalmagan |
| Benchmark natijalari | ⏳ hali o'tkazilmagan (faqat harness) |

Hech bir platforma "production-ready" deb belgilanmagan. Cheklovlar: [docs/LIMITATIONS.md](docs/LIMITATIONS.md).
