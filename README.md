# XADICHA AI

O'zbek, rus va ingliz tillaridagi tabiiy nutq hamda vizual kontekst asosida kompyuter interfeysini boshqaruvchi multimodal AI agent (magistrlik dissertatsiyasi loyihasi).

```
XADICHA AI/
├── backend/   ← Python agent: nutq, ekran, model, boshqaruv, xavfsizlik, FastAPI
└── src/       ← Next.js interfeys: yordamchi, dashboard, ekran tahlili, tarix, tadqiqot, sozlamalar
```

## Birinchi sozlash (bir marta)

```bash
cd ~/MAGISTRATURA/"XADICHA AI"/backend
source .venv/bin/activate
pip install -r requirements.txt     # google-genai (Gemini) shu yerda
cp .env.example .env                 # GEMINI_API_KEY ni yozing — kalit faqat backend/.env da
cd .. && npm install
```

Gemini, nutq (Gemini Transcribe / Whisper), Gemini Live, zaxira va macOS ruxsatlari:
[docs/VOICE_AND_GEMINI.md](docs/VOICE_AND_GEMINI.md).

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

Backend: Python 3.12, FastAPI, Pydantic, SQLite, Google Gemini (`google-genai`: generateContent, Google Search
grounding, Interactions/Transcribe, Live API), zaxira — Ollama (Qwen 3.5); Claude ham qo'llab-quvvatlanadi;
nutq — Gemini Transcribe yoki lokal Whisper (MLX / faster-whisper).
Interfeys: Next.js 16, Tailwind CSS 4, Motion, lucide-react; shadcn/ui, Magic UI va React Bits registrlari `components.json` da ulangan.

## Asosiy imkoniyatlar (hozirgi kod)

- **Gemini — asosiy AI** (`XADICHA_PROVIDER=gemini`): matn + ekran surati, agentning JSON formati. Model `.env` da
  sozlanadi (`GEMINI_MODEL`, standart `gemini-3.8-flash`), Gemini model zanjiri (`gemini-3.5-flash-lite`), keyin
  **Ollama zaxirasi** — tarmoq, timeout, 429, 5xx va kalit xatolarida; faol provayder statusda halol ko'rsatiladi.
- **AUTO qidiruv** (`XADICHA_SEARCH_MODE=auto|always|never`): dolzarb savollarda Google Search grounding — manbalar,
  qidiruv so'rovlari va Google Search Suggestions interfeysgacha; grounding ishlamasa DuckDuckGo/Wikipedia.
- **Oqimli buyruq STT** (`gemini-3.5-transcribe-live`): gapirayotganda jonli matn, gap tugagach birinchi amal
  ~0.3–0.9 s (real mikrofon / fayl o'lchovi, [docs/VOICE_LATENCY.md](docs/VOICE_LATENCY.md)); yiqilsa — oddiy yo'l.
- **STT** (`XADICHA_STT=auto|gemini|whisper`): Gemini Transcribe (`gemini-3.5-transcribe`) yoki lokal Whisper;
  maxsus lug'at va tuzatishlar; haqiqatan ishlagan provayder har bir natijada yoziladi.
- **Gemini Live** (`gemini-3.8-live`): real vaqtli ikki tomonlama ovoz, barge-in, sessiyani tiklash; desktop
  buyruqlari faqat mavjud agent (xavfsizlik + tasdiq) orqali.
- **Ish vaqtidagi sozlamalar** (Sozlamalar → Ishlash sozlamalari): qidiruv, STT, Live, ovoz, tezlik, mikrofon,
  lug'at, oflayn rejim — `backend/data/settings.json`; kalitlar hech qachon brauzerda emas.
- **A / B / C rejimlari** — tadqiqot uchun solishtiriladi (A: qoida, B: LLM reja, C: ekran + tekshiruv + tiklanish).
- **Ovoz** — mikrofonni faqat backend yozadi; Whisper (MLX / faster-whisper). Belgini bir marta bosasiz va gapirasiz:
  gapirib bo'lganingizni o'zi sezadi (jimlik) va aniq buyruqni darhol bajaradi. Nutq ishonchi va buyruq aniqligi alohida
  baholanadi; noaniq buyruqda eshitilgan matn ko'rsatiladi va foydalanuvchi tanlaydi (jimgina almashtirish yo'q).
- **Suhbat konteksti** — oxirgi 20 navbat va obyektlar (ilova, sayt, fayl, qidiruv natijalari): "uni yana och",
  "birinchisini och", "shu faylni ko'rsat", "yana bir marta". Sahifa yangilansa ham suhbat tiklanadi; "Yangi suhbat" tozalaydi.
- **Aqlli marshrutlash** — oddiy buyruq modelsiz (fast), qidiruv/fayl — maxsus vosita (tool), murakkab — LLM sikli (autonomous).
- **Internet qidiruvi** — DuckDuckGo HTML + Wikipedia (bepul, kalitsiz): haqiqiy sarlavha, manzil, parcha; javob faqat shu
  natijalardan, manbalar bilan. Fayl qidiruvi — faqat workspace ichida (Spotlight / os.walk).
- **Tizim boshqaruvi** — "ovozini ko'tar", "ovozni o'chir", "ovozni 40 ga qo'y", "yorug'likni oshir", "сделай тише",
  "brightness down" (uz lotin/kirill, ru, en): modelsiz, tasdiqsiz, darhol. Faqat aytilgan amal bajariladi.
- **Yagona holat** — sarlavha, yordamchi, vazifa paneli va dashboard bir manbadan (`phase`, `seq`).
- **Xavfsizlik** — Host/Origin/sessiya kaliti, xavf tasnifi, tasdiq, taqiqlangan yo'llar, log redaksiyasi ([docs/SECURITY.md](docs/SECURITY.md)).
- **Ekran** — surat + vision model; macOS'da ixtiyoriy OCR (Apple Vision) va accessibility daraxti (AXUIElement) — sinalmagan MVP.
- **3 tilli interfeys** — o'zbek, rus, ingliz; o'zbek kirill buyruqlari.
- **Benchmark** — 32 vazifa × 4 variant, xom loglar va metrikalar ([docs/RESEARCH_METHODOLOGY.md](docs/RESEARCH_METHODOLOGY.md)).

macOS uchun ixtiyoriy OCR/accessibility: `pip install -r backend/requirements-macos-optional.txt`.

## Tekshirish (testlar)

```bash
cd backend && source .venv/bin/activate && python -m pytest -q   # backend: 512 ta test (simulyatsiya)
python -m xadicha.speech_eval --text-only   # til/niyat/obyekt aniqligi (127 buyruq, 33 tur; matn, ASR'siz)
cd .. && npm test              # interfeys mantiqi: holat modeli, hodisalar, Live, jonli matn, tarjimalar (40 ta test)
npm run lint                   # ESLint
npm run typecheck              # TypeScript
npm run build                  # production build
```

Haqiqiy API sinovlari (internet + `GEMINI_API_KEY`; pytest tarkibiga kirmaydi):

```bash
cd backend && source .venv/bin/activate
python scripts/gemini_smoke.py                 # Gemini: model, JSON, rasm, agent qarori, grounding, Ollama zaxirasi
python scripts/gemini_live_smoke.py            # Gemini Live: uz/ru/en, tool chaqiruvi, barge-in (sintetik nutq)
python -m xadicha.validation.stt_compare       # STT: Gemini Transcribe vs Whisper, bir xil (sintetik) audio
python scripts/voice_latency_bench.py          # kechikish: eski vs oqimli zanjir, P50/P95 (--mic — real mikrofon)
python -m xadicha.validate speech --set heldout --speaker s01   # inson nutqi (rozilik bilan), ko'rilmagan to'plam
```

Real Mac'da tekshirish: `python backend/scripts/mac_selftest.py` — [docs/MACOS_TEST_PROTOCOL.md](docs/MACOS_TEST_PROTOCOL.md).
Interfeys dizayni (Liquid Glass, orb holatlari, vaqt chizig'i): [docs/DESIGN.md](docs/DESIGN.md).
Real o'lchovlar (nutq, ovoz, qidiruv, amallar, tezlik, A/B/C) va hisobot: `python -m xadicha.validate <qadam>` — [docs/REAL_VALIDATION.md](docs/REAL_VALIDATION.md).
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
| Mikrofon, TTS | ⚠️ real qurilmada avtomatik sinalmagan |
| Gemini provayderi (matn, rasm, agent qarori) | ✅ haqiqiy API (2026-11-25): JSON, rasm, 7 ta uz/ru/en/aralash buyruq; ⚠️ `gemini-3.8-flash` o'sha kuni 504 berdi — zanjir `gemini-3.5-flash-lite` ga o'tdi |
| Google Search grounding | ⚠️ kod va simulyatsiya testlari ✅; haqiqiy API **429** (bepul tarifda grounding kvotasi yo'q) — avtomatik DuckDuckGo zaxirasi haqiqiy tarmoqda ✅ |
| Ollama zaxirasi | ✅ haqiqiy: noto'g'ri kalit va uzilgan tarmoqda Ollama javob berdi |
| Gemini Transcribe / Whisper | ✅ haqiqiy API, sintetik nutq — natijalar `backend/validation/results/stt_compare-20261125/`; real odam nutqi WER ⏳ |
| Gemini Live | ✅ haqiqiy WebSocket, sintetik nutq: uz/ru/en, tool chaqiruvi, barge-in; real mikrofon bilan ⏳ (foydalanuvchi sinovi) |
| Claude provayderi | ⚠️ real model bilan avtomatik sinalmagan |
| Internet qidiruvi | ⚠️ tahlilchi namunaviy HTML bilan testlangan; real tarmoqda sinalmagan |
| Javoblarni oqim (streaming) bilan chiqarish | ❌ amalga oshirilmagan — halol "o'ylayapman" holati |
| A/B/C benchmark natijalari, real odam nutqi WER | ⏳ hali o'tkazilmagan (vositalar tayyor) |

Hech bir platforma "production-ready" deb belgilanmagan. Cheklovlar: [docs/LIMITATIONS.md](docs/LIMITATIONS.md).
