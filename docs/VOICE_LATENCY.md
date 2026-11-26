# Ovoz kechikishi — tahlil, optimallashtirish va o'lchovlar

Barcha raqamlar **haqiqiy o'lchov** (2026-11-25, shu Mac, haqiqiy Gemini API). Audio manbai har bir jadvalda
ko'rsatilgan: *fayl* — sintetik TTS nutqi real vaqt tezligida uzatilgan; *real mikrofon* — o'sha audio karnaydan
ijro etilib, MacBook mikrofoni havodan yozgan. Odam nutqi bilan o'lchov alohida (foydalanuvchi sinovi).

## 1. Eski zanjir va kechikish sabablari

```
mikrofon → VAD (0.9 s jimlik kutadi) → BUTUN audio → STT (unary) → router → amal → TTS (butun javob sintezi) → ijro
```

| # | Sabab | Ta'siri (o'lchov) |
|---|---|---|
| 1 | STT faqat gap tugagach boshlanadi (unary) | Gemini Transcribe ~2.4 s, Whisper (CPU) ~10–13 s yakuniy matngacha |
| 2 | Whisper o'zbek nutqini turkcha yozadi | intent noto'g'ri → amal yo'q (sintetik benchmark: intent 24–51%) |
| 3 | VAD 0.9 s jimlik kutadi | har buyruqqa +0.9 s |
| 4 | `gemini-3.8-flash` 504/timeout | birinchi LLM chaqiruvi +20 s (keyin zanjir flash-lite'ga o'tadi) |
| 5 | TTS butun javobni sintez qiladi, edge-tts har safar yangi ulanish | javob matnidan birinchi ovozgacha ~1.5–2 s |
| 6 | Ba'zi oddiy buyruqlar tezkor yo'lda yo'q | "Screenshot ol", "oxirgi yuklangan fayl" → LLM (sekunlar) |
| 7 | "Ovoz balandligini kamaytir" → `volume_up` (xato) | noto'g'ri amal |

## 2. Yangi zanjir

```
BUYRUQ REJIMI
mikrofon (16 kHz, mono, 16-bit, 64 ms bo'laklar, uzilmaydi)
   └─► WebSocket: gemini-3.5-transcribe-live ──► oraliq matn (UI'da jonli) ──► yakuniy matn
          (ulanish paytida audio buferda; yiqilsa — bufer Gemini Transcribe / Whisper'ga)
   └─► mahalliy VAD (0.6 s) — gap tugaganini tasdiqlaydi; yakuniy matn 1.2 s ichida kelmasa → oxirgi oraliq matn
router (tezkor yo'l: modelsiz) ──► registry + xavfsizlik ──► amal ──► javob ──► TTS: birinchi gap darhol, kesh

SUHBAT REJIMI (Live tugmasi)
Gemini Live (gemini-3.8-live): native audio ⇄, barge-in, sessiya konteksti; desktop amali → run_xadicha_command → agent
```

Ikki rejim: mikrofon tugmasi (buyruq) va "Live suhbat" tugmasi (suhbat) — bitta bosishda almashtiriladi; bir vaqtda
faqat bittasi mikrofonni ishlatadi.

### Qilingan optimallashtirishlar

| Optimallashtirish | Qayerda |
|---|---|
| Oqimli STT (interim + final), audio buferlash, xatoda buferni oddiy STT'ga berish | `speech/stream.py`, `service._stream_listen` |
| `audio_stream_end` ishlatilmaydi — jimlik oqimi bilan server tez yakunlaydi | o'lchov: 5–28 s → 0.6–0.9 s |
| Bo'lak o'lchami 64 ms (20 ms yakuniy matnni 12 s kechiktirdi) | `CHUNK_MS` |
| VAD 0.9 s → 0.6 s (oqimda) | `StreamingTranscriber` |
| Ishga tushishda DNS/TLS isitish (ulanish ~1.7 s → ~0.5 s) va ishlaydigan Gemini modelini aniqlash | `service.warmup`, `GeminiProvider.warmup` |
| Adaptiv timeout: yiqilgan model qayta 5 s timeout bilan sinaladi, cooldown eksponensial | `GeminiProvider._generate` |
| Oraliq matn ~12/s (oxirgi bo'lak tashlanmaydi) | `on_partial` |
| TTS: javob gaplarga bo'linadi — birinchi gap darhol; qisqa javoblar keshi | `speech/tts.py` |
| Tezkor router: skrinshot, oxirgi yuklangan fayl, "ovoz balandligini kamaytir" tuzatildi | `rule_based.py`, `router.py`, `tools/files.py` |
| Kechikish belgilari: har ovozli so'rovda `voice_latency` hodisasi va `task.data.latency` | `service._vmark/_vfinish` |

## 3. O'lchovlar

Buyruq: `python scripts/voice_latency_bench.py` (fayl audio) va `--mic` (real mikrofon). Natijalar:
`backend/validation/results/voice_latency-20261125/`.

### 3.1 Eski va yangi zanjir — bir xil 10 ta audio (fayl, real vaqt tezligida; uz 5, ru 2, en 3)

Vaqt mikrofon (oqim) boshidan; boshida 0.3 s jimlik, keyin ~2.5 s nutq. "Gapdan keyin" — audio tugagandan keyin.

| Ko'rsatkich (P50 / P95) | Yangi: oqimli Live Transcription | Eski: VAD 0.9 s → Whisper (CPU) |
|---|---|---|
| Birinchi oraliq matn (TTFT) | **1.60 s / 1.75 s** (foydalanuvchi hali gapirmoqda) | yo'q |
| Yakuniy matn | 3.73 s / 9.63 s* | 12.71 s / 14.98 s |
| Birinchi amal (TTFA) | **3.71 s / 4.02 s** | 12.57 s / 12.85 s |
| Gapdan keyin birinchi amalgacha | **0.88 s / 0.94 s** | ~10.2 s |
| Javob matni | 3.74 s / 4.04 s | 12.71 s / 14.99 s |
| Birinchi javob ovozi (edge-tts, keshsiz birinchi marta) | 4.98 s / 5.83 s | 12.71 s / 15.77 s |
| Amal muvaffaqiyati (TSR, tezkor buyruqlar) | **80%** (8/10) | 60% (6/10; o'zbekcha 1/5) |

\* Bitta namunada oqim matn qaytarmadi (14 s); ikki marta qayta o'lchanganda takrorlanmadi (3.8 s, 4.1 s).
Endi bunday holatda buferdagi audio avtomatik zaxira STT'ga beriladi. Yakunlash: server 2/10, oraliq matn 7/10
(7 tasining matni to'g'ri), bo'sh 1/10. Eski zanjirda Gemini Transcribe (unary) kvotasi tugagani uchun Whisper
o'lchangan; avvalgi STT benchmark'ida Gemini Transcribe yakuniy matni gap tugagach ~2.4 s (mediana) edi.

### 3.2 REAL MIKROFON (karnay → havo → MacBook Pro Microphone), oqimli zanjir, 3 ta o'zbekcha buyruq

| Namuna | Matn | Yakunlash | Ijro tugagach yakuniy matn | Ijro tugagach birinchi amal |
|---|---|---|---|---|
| Kalkulyatorni ishga tushir | ✅ to'g'ri | server | 18 ms | 267 ms |
| Notes ilovasini ochib ber | ✅ to'g'ri | server | 33 ms | 299 ms |
| Telegramni ochib qo'y | ✅ to'g'ri | oraliq | 340 ms | 452 ms |

P50 / P95: ijro tugagach birinchi amalgacha **0.30 s / 0.44 s**; birinchi oraliq matn 1.6–2.0 s (oqim boshidan).
Bu odam nutqi emas (sintetik ovoz karnaydan) — real foydalanuvchi bilan sinov alohida.

### 3.3 Qismlar bo'yicha (haqiqiy o'lchovlar)

| Bosqich | Qiymat |
|---|---|
| Live Transcription ulanishi | sovuq ~1.7 s, iliq ~0.5 s (ulanish paytida audio buferda — so'z yo'qolmaydi) |
| Bo'lak o'lchami | 20 ms: yakuniy matn 12 s kechikdi; 40/64/100 ms: 0.36–0.49 s — 64 ms tanlandi |
| `audio_stream_end` bilan yakunlash | 5–28 s (ishonchsiz) → ishlatilmaydi; jimlik oqimi bilan 0.64–0.92 s |
| Tezkor yo'l (router + amal, dry-run) | yakuniy matndan birinchi amalgacha ~3–250 ms |
| Javobning birinchi ovozi | edge-tts birinchi bo'lagi ~1.2–1.8 s; keshdagi qisqa javob ~0 ms |
| `/api/status` | 0.2 s (Whisper modeli CPU'da yuklanayotgan paytda sekinlashishi mumkin) |

## 4. Interfeys

* Buyruq rejimida kapsula ustida jonli matn (`stt_partial`) va mikrofon darajasi (haqiqiy `mic_level`).
* Xabar ostida til va STT provayderi ("UZ · Gemini Live"), `finalized_by=interim` bo'lsa ham metadata'da.
* "⏱ javob …" — oxirgi ovozli buyruqning birinchi amalgacha bo'lgan haqiqiy kechikishi; ustiga olib borilsa barcha
  bosqichlar (birinchi matn, yakuniy matn, amal, javob matni, javob ovozi).
* Holatlar (tinglash, tushunish, qidirish, bajarish, gapirish, tiklanish, xato) — faqat backend hodisalaridan.

## 5. Xavfsizlik va ishonchlilik

* Audio diskka yozilmaydi (bufer faqat xotirada, zaxira STT uchun). TTS keshi faqat 80 belgigacha bo'lgan **javob
  matnlari** ovozini saqlaydi (`backend/data/tts_cache`, 300 fayl, git'ga qo'shilmaydi) — foydalanuvchi ovozi emas.
* Oqim yiqilsa (tarmoq, kalit, kvota) — 120 s davomida oddiy yo'l; cheksiz qayta ulanish yo'q.
* Action registry, xavf darajalari, tasdiq, to'xtatish — o'zgarmagan; skrinshot past xavfli tizim amali.

## 6. Qo'shimcha (2026-11-26): doimiy sessiya, oqimli javob, butun to'plam

| O'lchov | Natija |
|---|---|
| Butun to'plam (68: uz 40, ru 14, en 14), oldindan ochilgan sessiya 59 tasida | ovoz tugagach birinchi amal P50 0.70 s / P95 1.14 s; yakuniy matn P50 0.57 s |
| Aniqlik (muvaffaqiyatli 59 ta) | WER 34.7%, CER 25.1%, intent 78%; uz WER (yozuvsiz) 31.4%, ru 17.7%, en 0% |
| Xato / bo'sh natija | 9 / 68 (4 ulanish timeout'i, 5 bo'sh) — ilovada bufer zaxira STT'ga beriladi |
| Oqimli javob (3 savol) | birinchi matn 0.63–0.67 s (eski: butun javob 2.1–6.5 s); birinchi ovoz 3.5–7.3 s — edge-tts 2.8–6.4 s |
| Bo'sh turgan sessiya (25 s) | to'g'ri ishladi — `LiveSTTPool` shunga asoslangan |

Qo'shilganlar: `LiveSTTPool` (oldindan ochilgan sessiya, mijozni qayta ishlatish), oqimli javob matni
(`generate_content_stream`) va gap-baqadam ovoz navbati, to'xtatishda oqimni uzish, vision modelda to'liq ekran
OCR'ini o'tkazib yuborish, lug'at (XADICHA AI, Gemini, Claude, Ollama, Terminal, Next.js, o'rnatilgan ilovalar;
fayl nomlari — faqat `XADICHA_VOCAB_FILES=1`), o'zbek apostrofi normalizatsiyasi.
Natijalar: `backend/validation/results/voice_latency-20261125/dataset_stream.json`.
