# Stage 0 — joriy holat auditi (2026-11-26)

Asos: `main` = `bb94ebc` (GitHub bilan sinxron, commit qilinmagan o'zgarish yo'q). Checkpoint teg: `checkpoint/stage0-20261126`.
Barcha "ishlaydi" da'volari quyidagi manbaga ega: **[T]** avtomatik test (simulyatsiya), **[A]** haqiqiy API sinovi,
**[M]** real mikrofon (karnay → havo → mikrofon, sintetik ovoz), **[D]** real desktop amali, **[—]** tekshirilmagan.

## 1. Joriy arxitektura

```
Next.js (Liquid Glass) ──HTTP+WS (localhost, token, origin)──► FastAPI (api.py) ──► XadichaService (service.py)
                                                                     │
  ovoz: MicSource → StreamingTranscriber (gemini-3.5-transcribe-live, LiveSTTPool) ─┐
        yoki Listener (VAD) → SpeechRecognizer (Gemini Transcribe | Whisper) ───────┤→ understand → Agent
  Live: LiveSession (gemini-3.8-live) ⇄ karnay; amal → run_xadicha_command ────────┘
                                                                     │
  Agent (agent.py): router (fast | tool | chat | clarify | autonomous)
     ├ fast/tool: rule_based → registry → safety → OSAdapter (macos/windows/dry-run)
     ├ chat: oqimli javob / Google Search grounding / DDG zaxira
     └ autonomous (C): ekran → Gemini qaror (JSON) → xavf → tasdiq → bajarish → tekshirish → tiklanish
  Provayderlar: FallbackProvider(Gemini [model zanjiri] → Ollama) | Claude | rule-based
  Xotira: Conversation (oxirgi 20 navbat, SQLite turns) · tarix: tasks (SQLite) · sozlamalar: data/settings.json
```

## 2. Ishlayotgan imkoniyatlar

| Imkoniyat | Dalil |
|---|---|
| Gemini qaror/reja (JSON, rasm), model zanjiri, adaptiv timeout | [T] [A] 7 ta ko'p tilli buyruq |
| Ollama zaxirasi (kalit xato, tarmoq yo'q) | [T] [A] |
| Oqimli STT: jonli matn, yakuniy matn, pool, bufer zaxirasi | [T] [A] 68 namuna, [M] 3/3 |
| Gemini Live: suhbat, barge-in, tool chaqiruvi | [T] [A] 5/5 (sintetik nutq) |
| Tezkor router: ilova, sayt, ovoz, yorqinlik, skrinshot, batareya, oxirgi yuklangan fayl | [T] [D] batareya (pmset) |
| Qidiruv: grounding kodi, DDG/Wikipedia zaxirasi | [T]; grounding [A] — 429 (bepul tarif) |
| Xavfsizlik: token, origin, redaksiya, subprocess muhiti, tasdiq, taqiqlangan yo'llar | [T] |
| Interfeys: holatlar, jonli matn, oqimli javob, kechikish, sozlamalar, 3 til | [T] node, headless brauzer (ekranlar) |

## 3. Tugallanmagan imkoniyatlar

- Inson nutqi bilan baholash: vosita bor (`validate speech`, faqat Whisper), lekin yozuvlar yo'q; oqimli/Gemini STT qo'llab-quvvatlanmaydi.
  *(Yangilandi 2026-11-27: ochiq FLEURS korpusida VAD va STT o'lchandi — [HUMAN_SPEECH_EVAL.md](HUMAN_SPEECH_EVAL.md); buyruqlar
  bo'yicha niyat/obyekt aniqligi uchun foydalanuvchi yozuvi hamon kerak.)*
- Vazifa grafi (bog'liqlik, parallel xavfsiz amallar) yo'q — agent qadamlar ketma-ket.
- Brauzer DOM (Playwright), ekran o'zgarishini aniqlash, ko'p monitor — yo'q.
- Accessibility rejimi (VoiceOver bilan sinov, ovozli tasdiq, verbosity) — yo'q; interfeysda faqat asosiy aria/klaviatura.
- Doimiy xotira (rozilik, tahrirlash) — yo'q; faqat suhbat konteksti va tarix.
- Claude: kod bor, [—] real sinov yo'q. Windows adapteri: [—].
- Narx (cost) kuzatuvi, provayder tanlash UI'si (faqat .env) — yo'q.

## 4. Tasdiqlangan xatolar

| # | Xato | Dalil | Bosqich |
|---|---|---|---|
| B1 | Oqimli STT'da server yakuniy matni kelmasa, **oraliq matn buyruq sifatida bajariladi** (`finalized_by=interim`) | kod: `service._stream_listen`; benchmark: 7/68 | ✅ Stage 1 da tuzatildi |
| B2 | Live karnaydan ijro paytida mikrofon ochiq — quloqchinsiz o'z ovozi bilan to'xtaydi (AEC yo'q) | hujjatlangan, [A] | ✅ Stage 1: standart — mikrofon gating |
| B3 | Oqimli STT 9/68 xato/bo'sh (4 ulanish timeout'i, 5 bo'sh) | [A] dataset | Stage 1 |
| B4 | Kirillda gapirilgan o'zbekcha matn lotinda qaytadi (yozuv saqlanmaydi) | [A] | ✅ Stage 1: yozuv afzalligi sozlamasi |
| B5 | Model amal bajarmay "bajarildi" deyishi mumkin (`done` + amalsiz) | [A] "ovozni 50 foizga tushir" (router endi ushlaydi) | Stage 3 |
| B6 | faster-whisper `decode_audio` o'rnatilgan PyAV bilan ishlamaydi (fayldan o'qish) | [A] | Stage 1 (muhit) |
| B7 | Whisper CPU'da (`mlx-whisper` o'rnatilmagan), o'zbekchani turkcha yozadi | [A] | muhit |
| B8 | Live: gap o'rtasidagi uzun pauza navbatni bo'ladi (ru) | [A] | Stage 5 |
| B9 | VAD fon darajasi nutq paytida nutq darajasiga "o'sib" ketadi (har bo'lakda EMA 0.05 — bo'lak o'lchamiga bog'liq) → real inson nutqi umuman sezilmaydi, yozuv 6 s da kesiladi | [H] foydalanuvchi sessiyasi 2026-11-26: 8/8 `no_speech` | ✅ 2026-11-27 ([HUMAN_SPEECH_EVAL.md](HUMAN_SPEECH_EVAL.md)) |
| B10 | Whisper nutqsiz audioda yordamchi so'rov gapini qaytaradi ("Play a song on YouTube.") — baholashda matn sifatida hisoblangan | [H] | ✅ 2026-11-27 |
| B11 | `--rescore` Gemini 429 (bepul tarif: 3 so'rov/daqiqa) da yiqiladi, hech narsa saqlanmaydi | [A] | ✅ 2026-11-27 |

## 5. Xavfsizlik

| Masala | Holat |
|---|---|
| Kalitlar backend'da, redaksiya, subprocess muhiti | ✅ [T], skaner: 155 fayl toza |
| Lokal API: token, Host/Origin, CORS | ✅ [T] |
| Workspace, taqiqlangan yo'llar | ✅ [T] |
| Prompt injection: veb natijalari, OCR matni, hujjatlar modelga "ma'lumot" sifatida aniq ajratilmagan | ⚠️ — xavfli amallar tasdiq bilan himoyalangan, lekin aniq "ishonchsiz kontent" belgisi yo'q (Stage 8) |
| Python bog'liqliklari zaiflik auditi (`pip-audit`) | ⚠️ o'tkazilmagan; `npm audit`: 0 |
| Fayl nomlari Gemini lug'atiga — faqat `XADICHA_VOCAB_FILES=1` | ✅ |

## 6. Kechikish to'siqlari (o'lchangan)

| To'siq | Qiymat |
|---|---|
| edge-tts birinchi gap | 1.2–6.4 s |
| Birinchi jonli matn (model) | P50 1.58 s |
| `gemini-3.8-flash` 504 (sinov kunlari) | +20 s (adaptiv timeout bilan 5 s) |
| Whisper zaxirasi (CPU) | ~10 s |
| C rejim qadami: ekran + LLM qarori | ~1–3 s / qadam |

## 7. Testlar va bo'shliqlar

Backend 589 (28 fayl), interfeys 41, tiplar, build ✅. Bo'shliqlar: inson nutqi korpusi yo'q; real desktop
avtomatik testlari yo'q (faqat `mac_selftest.py` qo'lda); E2E brauzer testlari CI'da yo'q; Windows va Claude
sinalmagan; accessibility (VoiceOver) sinovi yo'q; `pip-audit` yo'q.

## 8. Ustuvor yo'l xaritasi

1. **Stage 1** — B1 (oraliq matn bajarilmasin), B2 (Live aks-sado), B3/B4, transcript holati modeli, ishonchga
   asoslangan aniqlashtirish, inson nutqi korpusi (dev / regressiya / ko'rilmagan) va provayderlararo baholash.
2. **Stage 2** — provayder router (Claude murakkab reja uchun), narx/kechikish kuzatuvi, tanlash UI'si.
3. **Stage 3** — vazifa grafi, B5 (amalsiz "bajarildi"ni bloklash), audit izi.
4. **Stage 4** — Playwright (nazoratli), element-asosli interaksiya, ekran o'zgarishi.
5. **Stage 5** — TTS kechikishi (eng katta to'siq), adaptiv javob uzunligi.
6. **Stage 6** — accessibility rejimi va VoiceOver sinovi.
7. **Stage 7** — UI, rozilikka asoslangan xotira.
8. **Stage 8** — xavfsizlik auditi (prompt injection, pip-audit), benchmark, reliz.

## 9. Stage 1 da o'zgaradigan fayllar

`backend/xadicha/speech/stream.py`, `backend/xadicha/service.py`, `backend/xadicha/understand.py`,
`backend/xadicha/speech/live.py`, `backend/xadicha/settings.py`, `backend/xadicha/config.py`,
`backend/xadicha/validation/speech.py`, `backend/validation/human_*.csv` (yangi korpus), `backend/xadicha/metrics.py`,
`src/lib/i18n.ts`, `src/components/xadicha/runtime-settings.tsx`, testlar, `docs/STAGE1_REPORT.md`.


Stage 1 natijalari: [STAGE1_REPORT.md](STAGE1_REPORT.md).
