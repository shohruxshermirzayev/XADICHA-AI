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
