# Inson nutqi bilan baholash (2026-11-27)

Dalil belgilari: **[H]** haqiqiy inson nutqi, **[A]** haqiqiy API, **[T]** avtomatik test (simulyatsiya).

## 1. Birinchi real sessiya (2026-11-26) — natija yaroqsiz, sababi vositada

Foydalanuvchi (`s01`, tinch xona, MacBook Pro mikrofoni) ko'rilmagan to'plamdan 8 ta buyruq yozgan. Whisper natijasi:
WER 113%, niyat 0%. Tahlil ([user_session_diag-20261127.json](../backend/validation/results/user_session_diag-20261127.json)):

| Belgi | Topilgan |
|---|---|
| Har bir yozuv | aniq 6.0 s — VAD `no_speech` (nutq sezilmadi), yozuv vaqt chegarasida kesilgan |
| Gemini Transcribe (o'sha audio) | 4/8 da faqat «Xadicha», 4/8 bo'sh — buyruqning o'zi yozuvga to'liq tushmagan |
| Whisper gipotezalari | «Play a song on YouTube.» (2 marta), «See you next time.», «Pobre. Pobre. Pobre.» — yordamchi so'rovdan aks-sado va xayolot |
| VAD qayta ijrosi (yozuvlar bo'yicha) | fon darajasi 0.004 → 0.12 gacha ko'tarilgan (nutq darajasidan yuqori) |

**Xulosa:** bu sessiya STT sifatini emas, vosita xatolarini o'lchagan. U benchmark sifatida ishlatilmaydi.

### Topilgan va tuzatilgan xatolar

| # | Xato | Tuzatish |
|---|---|---|
| B9 | VAD fon darajasini nutq paytida ham ko'tarardi: har bo'lakda EMA 0.05 — 10 ms bo'laklarda vaqt doimiysi 0.2 s; nutqning sokin qismlari fonni nutq darajasiga olib chiqib, chegara nutqdan yuqori bo'lib qolardi. Bu **ilovadagi ovozli kiritishga ham** ta'sir qilardi (`service.py`, oqimli STT) | Vaqtga asoslangan kuzatuv: fon pastga tez (τ 0.4 s, faqat nutqdan tashqarida), yuqoriga sekin (τ 4 s) harakatlanadi; mikrofon bo'lagi aniq 32 ms; qisqa tovushdan (<0.35 s: nafas, stul) keyin 2 s kutiladi; mutlaq minimal daraja 0.008 → 0.001 (sokin mikrofon) |
| B10 | Whisper nutqsiz audioda yordamchi so'rov gapini qaytarardi — baholashda matn sifatida hisoblanardi | VAD nutq sezmagan yozuvda so'rov gapi (ishonch < 0.55) tashlanadi — ilovada va vositada bir xil qoida; bitta so'z takrori (ishonch past) har doim tashlanadi. Ishonchi past haqiqiy buyruq («Telegramni och») tashlanmaydi — avvalgidek tasdiq so'raladi |
| B11 | `--rescore` Gemini 429 da yiqilardi, hech narsa saqlanmasdi | Har yozuv alohida: kvotada xabardagi «retry in N s» bo'yicha kutib qayta urinadi; boshqa xato `provider_error` bilan yoziladi va WER'ga kirmaydi |
| — | Yozish vositasi nutq sezilmasa ham davom etardi | Sessiya boshida mikrofon tekshiruvi; «🎙 GAPIRING» belgisi; nutq sezilmasa — «qayta yozish / shunday saqlash» |

Ilovada past ishonchli matn avvaldan ham bajarilmasdi (`understand`: ishonch < 0.55 → tasdiq so'raladi), shuning uchun
xayolot matni hech qachon amal sifatida bajarilmagan — xato baholash natijasini buzgan.

## 2. Foydalanuvchisiz baholash: Google FLEURS (ochiq inson nutqi)

**FLEURS** — ko'p ishtirokchidan rozilik bilan yig'ilgan haqiqiy o'qilgan nutq (Wikipedia gaplari), o'zbek, rus va
ingliz tillarida. Manba: [google/fleurs](https://huggingface.co/datasets/google/fleurs), Conneau va boshq., 2022,
*FLEURS: Few-shot Learning Evaluation of Universal Representations of Speech*; litsenziya **CC BY 4.0**.

```bash
cd backend && source .venv/bin/activate
python -m xadicha.validate fleurs --download --split dev  --per-lang 60   # sozlash uchun
python -m xadicha.validate fleurs --download --split test --per-lang 30   # yakuniy o'lchov
python -m xadicha.validate fleurs --vad --split test                       # VAD — mahalliy, API'siz
python -m xadicha.validate fleurs --stt --split test --providers whisper,gemini-live
```

Arxiv butunicha yuklanmaydi — oqimdan dastlabki N ta yozuv olinadi (bir gapning faqat bitta o'quvchisi, ≤ 25 s).
Audio `backend/data/fleurs/` da (git'ga qo'shilmaydi), tanlangan yozuvlar ro'yxati —
`backend/validation/fleurs_{dev,test}_sample.csv`.

**Metodika:** VAD parametrlari faqat `dev` (180 yozuv) da tanlangan; `test` (90 yozuv: 30 uz, 30 ru, 30 en) —
o'lchov uchun. Ochiq qayd — `test` uch marta ishga tushirildi, har biri saqlangan:

1. `fleurs_test_vad-20261127-142216.json` — benchmark'ning o'zida nomuvofiqlik topildi: qo'shilgan fon shovqini
   yozuvning nutqdan oldingi jimligidan 2–6 barobar baland edi (bir xonada bunday bo'lmaydi). Benchmark tuzatildi
   (VAD emas), `dev` da parametrlar qayta tekshirildi — o'zgarmadi.
2. `…-142734.json` — tuzatilgan benchmark bilan.
3. `…-150412.json` — **yakuniy**. STT o'lchovida FLEURS en yozuvlarining 19/30 i juda past darajada ekani (cho'qqi
   < 0.05) va VAD bunday nutqni sezmasligi ko'rindi. `dev` ga «juda past daraja» va «sokin xona» (taqillash, sekin
   ortuvchi fon) holatlari qo'shildi; `dev` da mutlaq minimal daraja 0.005 → 0.001 tanlandi (boshqa holatlar
   o'zgarmadi yoki yaxshilandi, soxta «nutq» 0%); `test` bir marta qayta o'lchandi.

### Cheklovlar

- O'qilgan gaplar, buyruq emas — **niyat/obyekt aniqligi o'lchanmaydi**.
- Foydalanuvchining o'z ovozi, mikrofoni va xonasi o'rnini bosmaydi.
- VAD holatlari (mikrofon darajasi, gapdan oldingi jimlik, shovqin) asl yozuvga sun'iy qo'llangan; nutqning o'zi haqiqiy.
- Gemini bilan baholashda ochiq to'plam audiosi Google'ga yuboriladi.

## 3. VAD natijalari — FLEURS `test`, 90 ta haqiqiy yozuv [H]

To'g'ri yakunlash ulushi, % (nutq sezildi, gap oxirigacha yozildi va jimlikdan keyin to'xtadi). Bo'lak o'lchami:
10 ms — eski kodda drayver tanlashi mumkin bo'lgan o'lcham; 32 ms — `Listener` (endi aniq); 64 ms — oqimli STT.
«Qisqa» — gapning dastlabki 2 soniyasi (buyruq uzunligi).

| Holat | 10 ms: eski → yangi | 32 ms: eski → yangi | 64 ms: eski → yangi |
|---|---|---|---|
| Oddiy (yaqin mikrofon, cho'qqi 0.5) | 94.4 → **100.0** | 92.2 → **97.8** | 92.2 → **98.9** |
| Sokin mikrofon (cho'qqi 0.12) | 76.7 → **98.9** | 84.4 → **96.7** | 85.6 → **97.8** |
| Juda past daraja (cho'qqi 0.02) | 0.0 → **94.4** | 0.0 → **95.6** | 0.0 → **96.7** |
| Enter bilan darhol gapirish | 93.3 → **95.6** | 95.6 → **95.6** | 94.4 → **96.7** |
| Shovqin (SNR 15 dB) | 62.2 → **92.2** | 80.0 → **93.3** | 90.0 → **94.4** |
| Qisqa buyruq (2 s) | 93.3 → **100.0** | 92.2 → **98.9** | 93.3 → **100.0** |
| Qisqa, darhol gapirish | 90.0 → **97.8** | 92.2 → **97.8** | 92.2 → **98.9** |
| Qisqa, sokin mikrofon | 83.3 → **100.0** | 90.0 → **98.9** | 93.3 → **100.0** |

| Ko'rsatkich (eng yomon bo'lak o'lchami) | Eski | Yangi |
|---|---|---|
| Nutq umuman sezilmadi — shovqinda | 35.6% | 4.4% |
| Nutq umuman sezilmadi — sokin mikrofonda | 14.4% | 1.1% |
| Erta kesildi — oddiy / sokin mikrofon | 6.7% / 11.1% | 1.1% / 2.2% |
| Erta kesildi — qisqa buyruqlar | 3.3–5.6% | **0%** |
| Nutqsiz holatda «nutq» sezildi (5 holat: barqaror, sekin ortuvchi fon, taqillash; oddiy va sokin xona) | 0% | 0% |
| Gap tugagach to'xtashgacha (P50) | 0.87–1.25 s | 1.16–1.40 s |

**Narxi:** gap tugagach to'xtash P50 ≈ 0.1–0.3 s kechroq. Sabab: so'z oxiridagi sokin tovushlar endi nutq deb
tanilyapti (erta kesilish kamaygani shundan) va ko'proq gap «uzun gap» pauzasini (1.2 s) oladi. Kechikishni
qisqartirish — Stage 5 (kechikish) vazifasi.
Foydalanuvchi yozuvlari (2026-11-26) yangi VAD bilan oflayn qayta ijroda nutq sezildi: 6/8 (eskisi jonli sessiyada 0/8).

## 4. STT natijalari — FLEURS `test` [H] [A]

90 yozuv (30 uz, 30 ru, 30 en), bir xil audio. Whisper — `large-v3-turbo` (faster-whisper, CPU), butun yozuv;
Gemini Live — `gemini-3.5-transcribe-live`, real vaqt oqimi (ilovadagi kabi, mahalliy VAD bilan).
Natijalar: `fleurs_test-20261127-145817.json` (Whisper), `fleurs_test-20261127-145742.json` (Gemini Live).

| Til | Whisper WER / CER | Gemini Live WER / CER (tugagan sessiyalar) | Gemini Live: faqat server yakuniy matni |
|---|---|---|---|
| O'zbek | 98.0% / 42.9% | **18.6% / 10.1%** (26) | 18.6% (26) |
| Rus | **6.1% / 1.4%** | 17.2% / 14.9% (27) | 7.3% (22) |
| Ingliz | **6.1% / 3.4%** | 33.9% / 33.5% (17) | 1.1% (6) |
| Til aniqlash | 98.9% | 97.1% | — |

| Gemini Live sessiya holati | uz | ru | en |
|---|---|---|---|
| Server yakuniy matni (`final`) | 26 | 22 | 6 |
| Mahalliy yakunlangan (`local` — ilovada tasdiq so'raladi) | 0 | 5 | 11 |
| Ulanish/javob kutish xatosi («javob kutish vaqti tugadi») | 4 | 3 | 13 |

Xulosalar:

- **O'zbek tili uchun Gemini aniq ustun** (WER 18.6% vs 98%). Whisper o'zbekchani turkcha imlo bilan yozadi
  («Kirchner khanım … presidentlikke») — bu yozuv muammosi emas, tanish xatosi (B7). Rus va ingliz tilida
  Whisper juda yaxshi (6%).
- **Gemini Live oqim xatolari: 20/90 (22%)** — barchasi bir xil (javob kutish vaqti), o'lchov oxiriga qarab
  ko'paygan (en oxirgi navbatda edi) — xizmat tomonidagi cheklov ehtimoli. Ilovada bunday holatda buferdagi
  audio oddiy STT'ga beriladi (buyruq yo'qolmaydi), lekin bu B3 ni tasdiqlaydi — Stage 2.
- Ingliz tilidagi `local` holatlar asosan **juda past darajadagi yozuvlar** (19/30 da cho'qqi < 0.05): bu o'lchovda
  oqimli VAD'ning minimal darajasi 0.005 edi va bunday nutqni sezmay 6 s da to'xtatardi. Minimal daraja 0.001 ga
  tushirildi (3-bo'lim); u bilan qayta o'lchov 51/90 yozuvda sessiya tugashi sababli uzildi va saqlanmadi —
  **yangi sozlama bilan STT natijasi hali o'lchanmagan**.
- `asr_ms` bu yerda kechikish emas: oqim real vaqtda uzatilgani uchun yozuv davomiyligini o'z ichiga oladi.

## 5. Foydalanuvchi uchun qolgan ish

Buyruqlar bo'yicha niyat/obyekt aniqligi va o'z ovozingiz/mikrofoningiz uchun bitta qisqa sessiya (≈ 5 daqiqa) kerak —
endi vosita mikrofonni oldindan tekshiradi va nutq sezilmasa qayta yozishni taklif qiladi:

```bash
cd backend && source .venv/bin/activate
python -m xadicha.validate speech --set heldout --speaker s01 --env quiet --speed normal
python -m xadicha.validate speech --rescore validation/results/speech-<vaqt> --providers whisper,gemini-live
```
