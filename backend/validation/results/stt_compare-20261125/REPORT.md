# STT taqqoslash — 2026-11-25T17:54:35

**Audio: sintetik (edge-tts neyron ovozlari), odam nutqi emas.** Real mikrofon aniqligi alohida o'lchanadi.
Namunalar: 72 × 1 ovoz · til prior: `uz` · provayderlar: whisper (faster:large-v3-turbo), gemini (gemini-3.5-transcribe)

| Ko'rsatkich | gemini | whisper |
|---|---|---|
| WER | 24.6% | 52.7% |
| CER | 12.8% | 25.1% |
| WER (uz, yozuvdan qat'i nazar) | 30.4% | 93.8% |
| So'z aniqligi (1−WER) | 75.4% | 50.4% |
| Til aniqlash | 100.0% | 92.5% |
| Intent aniqligi | 76.2% | 50.9% |
| Kechikish, mediana (ms) | 2421 | 9979 |
| Kechikish, p90 (ms) | 2780 | 10705 |
| Urinishlar | 53 | 53 |
| API xatosi (aniqlikka kirmagan) | 32 | 0 |
| Xato/bo'sh natija | 60.4% | 0.0% |
| Jimlikda matn to'qish | — | — |

## Guruhlar bo'yicha (til-yozuv)

**gemini**

| Guruh | n | WER | CER | WER (yozuvsiz) | Til | Intent |
|---|---|---|---|---|---|---|
| en-latn | 1 | 0.0% | 0.0% | — | 100.0% | 100.0% |
| ru-cyrl | 3 | 0.0% | 0.0% | — | 100.0% | 100.0% |
| uz-cyrl | 2 | 75.0% | 83.3% | 75.0% | 100.0% | 0.0% |
| uz-latn | 15 | 24.4% | 6.8% | 24.4% | 100.0% | 80.0% |

**whisper**

| Guruh | n | WER | CER | WER (yozuvsiz) | Til | Intent |
|---|---|---|---|---|---|---|
| en-latn | 14 | 0.0% | 0.0% | — | 100.0% | 100.0% |
| ru-cyrl | 9 | 0.0% | 0.0% | — | 100.0% | 100.0% |
| ru-mixed | 2 | 33.3% | 35.1% | — | 100.0% | 50.0% |
| uz-cyrl | 3 | 100.0% | 91.6% | 100.0% | 33.3% | 33.3% |
| uz-latn | 25 | 97.1% | 39.3% | 93.1% | 92.0% | 8.0% |

Gemini taqqoslashda zaxirasiz chaqiriladi (Whisper'ga o'tmaydi); API xatosi bergan namuna aniqlik
metrikalariga kirmaydi, faqat xato darajasida hisoblanadi. O'zbek kirill namunalari sintez uchun lotinga
o'girilgan (bir xil nutq); referens kirillda — shuning uchun yozuvdan qat'i nazar WER alohida berilgan.
Intent aniqligi: router mos yozuv (referens) va natijadan bir xil yo'l/intent/harakat chiqaradimi.
Til aniqlash: Gemini tilni matndan aniqlaydi (`detect_text_language`), Whisper — o'z ehtimolliklaridan.

## Juft taqqoslash — bir xil 21 ta audio (Gemini haqiqatan javob bergan namunalar)

Guruhlar: {'uz-latn': 15, 'uz-cyrl': 2, 'ru-cyrl': 3, 'en-latn': 1}

| Ko'rsatkich | gemini | whisper |
|---|---|---|
| WER | 24.6% | 81.7% |
| CER | 12.8% | 38.4% |
| WER (uz, yozuvsiz) | 30.4% | 99.0% |
| Til aniqlash | 100.0% | 90.5% |
| Intent aniqligi | 76.2% | 23.8% |
| Kechikish, mediana (ms) | 2421 | 9963 |

**Muhim:** birinchi yugurishda Gemini Transcribe 21 so'rovdan keyin bepul tarif kvotasiga yetdi (429);
qolgan 32 namunada Whisper zaxirasi ishlagan — ular Gemini aniqligidan chiqarildi (yuqoridagi asosiy jadvalda
"API xatosi" sifatida). 19 namuna (4 jimlik, 11 o'zbek kirill, 4 rus) TTS sintezi xatosi tufayli o'lchanmadi —
sintez tuzatildi; to'liq qayta o'lchash kvota tiklangach: `python -m xadicha.validation.stt_compare`.
Whisper bu Mac'da faster-whisper (CPU) da ishladi — MLX (GPU) o'rnatilmagan; kechikish shunga mos.
