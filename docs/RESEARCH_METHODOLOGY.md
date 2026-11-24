# Tadqiqot metodologiyasi

Bu hujjat **qanday o'lchanishini** tasvirlaydi. Hozircha real qurilmada benchmark o'tkazilmagan — natijalar yo'q.

## Savol

Ekran konteksti, tekshiruv va tiklanish (C rejimi) faqat buyruqqa asoslangan usullarga (A, B) nisbatan o'zbek, rus va
ingliz tillarida kompyuterni boshqarish vazifalarini ishonchliroq bajaradimi — xavfsizlikni pasaytirmasdan?

## Taqqoslanadigan usullar

| Rejim | Tavsif |
|---|---|
| A | qoida asosida, bitta harakat, ekransiz, tekshiruvsiz (bazaviy) |
| B | LLM bir martalik reja, ekransiz, tekshiruvsiz |
| C | LLM har qadamda: ekran surati (+ ixtiyoriy OCR/AX), dasturiy + vizual tekshiruv, tiklanish |

Uchala rejim bir xil xavfsizlik qatlami, bir xil model va bir xil vazifalar bilan ishlaydi.

## Vazifalar

`backend/benchmark/tasks.json` — 32 vazifa × 4 variant (o'zbek lotin, o'zbek kirill, rus, ingliz) = 128 buyruq.
Toifalar: ilova ochish (10), sayt ochish (3), qidiruv (3), papka/fayl yaratish (5), ko'p qadamli (4), ekran savoli (2),
xavfsizlik (5). Har bir vazifada: `reference_intent`, `expected` (haqiqiy natijani tekshirish turi), `must_confirm` / `must_block`.

## Metrikalar (`backend/xadicha/metrics.py`)

| Metrika | Ta'rif |
|---|---|
| TSR | haqiqiy natija tekshiruvi o'tgan vazifalar / avtomatik tekshiriladigan vazifalar × 100% |
| Intent accuracy | `task.intent` = `reference_intent` (ko'p qadamli vazifalar hisobga olinmaydi) |
| Verification accuracy | agentning "muvaffaqiyatli" da'vosi haqiqiy tekshiruvga mos kelgan ulush |
| Recovery success rate | kamida bitta qadami yiqilgan vazifalar ichida oxir-oqibat haqiqatan bajarilganlar |
| Safety compliance | xavfsizlik vazifalarida taqiqlangan harakat bajarilmagan va tasdiq so'ralgan ulush |
| Latency | buyruqdan yakuniy javobgacha (median, o'rtacha); taqsimot: model / ekran / bajarish |
| WER / CER | Levenshtein; tinish belgilarisiz; faqat ma'lumotnoma matni bor nutq yozuvlari uchun |

"Haqiqiy natija" agentdan mustaqil tekshiriladi: old plandagi ilova (`frontmost_app`), papka/fayl mavjudligi,
bajarilgan `open_url` manzili, taqiqlangan harakat bajarilmagani. `answer_only` (ekran savoli) — inson baholaydi; TSR'ga kirmaydi.

## Protsedura

1. Bir xil Mac, bir xil model (`OLLAMA_MODEL` yoki `CLAUDE_MODEL`), `.env` qayd etiladi.
2. Har vazifadan oldin bir xil boshlang'ich holat: barcha oynalar yopiq, Finder old planda; `workspace/xadicha-bench` bo'sh.
3. `python -m xadicha.benchmark --modes A,B,C --langs uz,uz_cyrl,ru,en` — har qator xom log (JSONL) sifatida yoziladi.
4. Har konfiguratsiya kamida 3 marta (model tasodifiyligi). Xom loglar saqlanadi, tahrirlanmaydi.
5. Metrikalar: `python -m xadicha.benchmark --summarize benchmark/results/run-*.jsonl`.
6. Nutq: har til uchun ma'lumotnoma jumlalari yoziladi (`scripts/mac_selftest.py --only speech`), WER/CER hisoblanadi.

Tasdiq siyosati benchmark davomida avtomatik va konservativ: faqat benchmark papkasi ichidagi o'rta xavfli amallar
tasdiqlanadi; yuqori xavfli har qanday amal rad etiladi.

## Nutq tajribasi (real audio)

1. `benchmark/speech_manifest.csv` dagi har bir qatorni (`id`) kamida 2 ta ma'ruzachi, tinch va shovqinli xonada o'qiydi;
   fayl nomi `<id>__<speaker>__<quiet|noisy>.wav` → baholashdan oldin `<id>.wav` papkalariga ajratiladi.
2. Modellar bir xil yozuvlarda solishtiriladi: `large-v3-turbo`, `small` (faster-whisper va MLX).
3. O'lchanadi: WER, CER, LID, niyat aniqligi, RTF, yuklash vaqti, xotira; `mac_selftest.py --only vad` — endpoint kechikishi.
4. ASR ishonch chegarasi (`ASR_LOW = 0.55`) shu yozuvlarda kalibrlanishi kerak — hozircha taxminiy.

## Validlikka tahdidlar

- Vazifalar to'plami muallif tomonidan tuzilgan; real foydalanuvchi buyruqlarini to'liq aks ettirmaydi.
- Ilova nomlari macOS'ga xos; Windows natijalari alohida o'lchanishi kerak.
- Model tasodifiyligi — takroriy ishga tushirishlar va ishonch oraliqlari kerak.
- `url_opened` brauzerda sahifa haqiqatan yuklanganini emas, buyruq berilganini tekshiradi.
- Matnli buyruqlar ASR xatolarini o'z ichiga olmaydi; ovozli tajriba alohida o'tkazilishi kerak.

## Natijalarni ajratish

| Toifa | Qayerda |
|---|---|
| Amalga oshirilgan imkoniyatlar | README, ARCHITECTURE |
| Simulyatsiya test natijalari | `pytest`, `npm test`, `--dry-run` (`"simulated": true`) |
| Real qurilma natijalari | `backend/data/selftest-*.json`, `benchmark/results/*.jsonl` (simulated: false) |
| Rejadagi ishlar | LIMITATIONS.md |
