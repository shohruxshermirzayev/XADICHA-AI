# Testlash

## Buyruqlar

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                 # backend (simulyatsiya)

cd ..
npm test                            # interfeys mantiqi (node --test): holat, hodisalar, tarjimalar
npm run lint
npm run typecheck
npm run build
```

## Nima simulyatsiya, nima real

| Tur | Qayerda | Haqiqiy qurilma? |
|---|---|---|
| Backend unit/integratsiya | `backend/tests/` | **Yo'q** — `DryRunAdapter`, `ScriptedProvider`, soxta mikrofon/OCR/AX |
| Interfeys mantiqi | `src/lib/__tests__/` | Yo'q — sof funksiyalar |
| Brauzer E2E | headless Chrome + dry-run backend (repo'da skript yo'q, natijalar commit xabarida) | Yo'q — Linux, dry-run |
| Benchmark `--dry-run` | `python -m xadicha.benchmark --dry-run` | Yo'q — faqat harness tekshiruvi, natija emas |
| macOS tekshiruvi | `backend/scripts/mac_selftest.py` | **Ha** — foydalanuvchi o'z Mac'ida ishga tushiradi |
| Real validatsiya | `python -m xadicha.validate …` ([REAL_VALIDATION.md](REAL_VALIDATION.md)) | **Ha** — natijalar `backend/validation/results/`, hisobot `REPORT.md` |
| Benchmark (real) | `python -m xadicha.benchmark` (macOS) | Ha — hali o'tkazilmagan |

## Backend test fayllari

| Fayl | Tekshiradi |
|---|---|
| `test_agent.py` | A/B/C sikli, tiklanish, qadam chegarasi |
| `test_safety.py`, `test_regressions.py` | xavf, taqiqlar, yo'l aylanib o'tish, tasdiq, mikrofon xatolari |
| `test_state.py` | yagona holat (`seq`, `phase`), "band" osilib qolmasligi, to'xtatish |
| `test_security.py` | Host, Origin, sessiya kaliti, WebSocket, validatsiya, log redaksiyasi |
| `test_understand.py` | ASR/niyat ishonchi, aniqlashtirish, uz lotin/kirill, ru, en, aralash til |
| `test_context.py` | koordinata masshtabi, OCR/AX provayder interfeysi va holati |
| `test_benchmark.py` | WER/CER, metrikalar, vazifalar to'plami, harness |
| `test_intelligence.py` | til aniqlash, havolalar ("uni yana och"), marshrutlash, o'zbek korpusi, qidiruv tahlilchisi (namunaviy HTML), fayl qidiruvi, qayta urinish bloki, vaqt chegarasi, vaqt izi, suhbat saqlanishi, TTS ovoz tanlash, VAD |
| `test_voice_control.py` | ovoz/yorqinlik buyruqlari, avtomatik to'xtash, avtomatik bajarish |
| `test_api.py`, `test_core.py`, `test_robustness.py`, `test_rule_based.py`, `test_stt.py` | API, saqlash, model javoblari, qoida tahlili, STT |

## Interfeys test fayllari

`state.test.mjs` (hodisalar tartibi, eskirgan HTTP javoblari, qayta ulanish, backend qayta ishga tushishi),
`events.test.mjs` (noto'g'ri xabarlar, qayta ulanish kechikishi), `i18n.test.mjs` (kalitlar to'liqligi, kirill aniqlash).

## Til va niyat baholash

`python -m xadicha.speech_eval --text-only` — `benchmark/speech_manifest.csv` (127 buyruq, 33 tur, uz lotin/kirill, ru, en).
Real audio: yozuvlarni `<id>.wav` (16 kHz mono) nomi bilan saqlang → `python -m xadicha.speech_eval --audio-dir DIR
--models large-v3-turbo,small --engines mlx,faster` — WER, CER, LID, niyat, RTF, xotira.

## Natijalarni qayd etish

Real qurilma natijasini yozganda: OS versiyasi, qurilma, provayder/model, `.env` sozlamalari, buyruq, kuzatilgan natija,
xato matni. `mac_selftest.py` buni JSON'ga avtomatik yozadi (`backend/data/selftest-*.json`).
Simulyatsiya natijalarini hech qachon real qurilma natijasi deb ko'rsatmang.

## Gemini, STT, Live, sozlamalar (2026-11)

| Tur | Fayl / buyruq | Nima |
|---|---|---|
| Unit + mock integratsiya | `tests/test_gemini.py` | Provayder yaratish, kalit o'qish, javob/rasm, xato tasnifi, model zanjiri, AUTO/ALWAYS/NEVER, grounding metadata → API, Ollama zaxirasi, redaksiya |
| Unit + mock integratsiya | `tests/test_stt_providers.py` | Gemini Transcribe so'rovi, lug'at, til aniqlash (uz lotin/kirill, ru, en, aralash), Whisper zaxirasi, cooldown, service hodisalari |
| Mock integratsiya | `tests/test_live.py` | Live sessiya: audio oqimi, barge-in, `go_away` + resumption, tool chaqiruvi, xatolar, API |
| Mock integratsiya | `tests/test_settings.py` | Sozlamalar API, tekshiruv (kalit rad etiladi), saqlash, oflayn rejim, `/api/health` |
| Unit | `tests/test_multilingual_examples.py` | 8 ta aralash tilli misol: marshrut, til, murojaat so'zi, ovoz miqdori |
| Interfeys (node) | `src/lib/__tests__/voice.test.mjs` | Live hodisalari, holat o'tishlari, orb holatlari (soxta faollik yo'q) |
| **Haqiqiy API** | `scripts/gemini_smoke.py` | Gemini model, JSON, rasm, agent qarori, grounding, Ollama zaxirasi (kalit / tarmoq) |
| **Haqiqiy API** | `scripts/gemini_live_smoke.py` | Live WebSocket: uz/ru/en, tool, barge-in — sintetik nutq bilan |
| **Haqiqiy API** | `python -m xadicha.validation.stt_compare` | Gemini Transcribe vs Whisper, bir xil sintetik audio, WER/CER/til/intent/kechikish |
| Real mikrofon | — | ⏳ foydalanuvchi bilan (Live va oddiy ovoz) |
| Real desktop amali | — | ⏳ `scripts/mac_selftest.py` (mavjud protokol) |

Mock testlar tarmoqqa chiqmaydi va haqiqiy API natijasi deb hisoblanmaydi.

## Oqimli ovoz va kechikish (2026-11)

| Tur | Fayl / buyruq | Nima |
|---|---|---|
| Mock integratsiya | `tests/test_streaming.py` | Oqimli STT (interim/final, kech yakunlash, xato → bufer zaxirasi, bo'sh natija), kechikish belgilari, tezkor router, TTS bo'laklari, adaptiv timeout |
| Interfeys (node) | `src/lib/__tests__/voice.test.mjs` | `stt_partial` (faqat tinglashda), `voice_latency` (o'lchanmagan qiymat — null) |
| **Haqiqiy API** | `scripts/voice_latency_bench.py` | Eski vs yangi zanjir, fayl audio, P50/P95 |
| **Real mikrofon** | `scripts/voice_latency_bench.py --mic` | Karnay → havo → mikrofon; odam nutqi emas |
