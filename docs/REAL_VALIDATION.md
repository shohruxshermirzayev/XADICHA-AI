# Real MacBook validatsiyasi

Bu hujjat XADICHA AI ni haqiqiy Mac'da — real mikrofon, real ovoz, real internet va real macOS amallari bilan —
qanday o'lchashni tushuntiradi. Avtomatik testlar (pytest, e2e) simulyatsiya; ular bu yerda natija sifatida
hisoblanmaydi. O'tkazilmagan har bir sinov hisobotda **NOT TESTED** bo'lib qoladi.

Barcha buyruqlar `backend` papkasida, virtual muhit faol holda:

```bash
cd ~/MAGISTRATURA/"XADICHA AI"/backend
source .venv/bin/activate
pip install -r requirements.txt -r requirements-macos-optional.txt   # bir marta
```

Ollama ishlab turishi kerak (`ollama serve`, model: `ollama pull qwen3.5:9b`).

## Tartib

| # | Buyruq | Siz nima qilasiz | Vaqt |
|---|---|---|---|
| 1 | `python -m xadicha.validate env` | hech narsa — faqat o'qiydi | 10 s |
| 2 | `python -m xadicha.validate speech` | 64 ta qatorni ovoz chiqarib o'qiysiz | 15–20 daq |
| 3 | `python -m xadicha.validate tts` | har iborani tinglab 1–5 baho berasiz | 10–20 daq |
| 4 | `python -m xadicha.validate automation` | boshlashga ruxsat, tasdiqlarga javob; klaviaturaga tegmaysiz | 5 daq |
| 5 | `python -m xadicha.validate search --judge` | har javob manbaga mosmi — y/n | 5 daq |
| 6 | `python -m xadicha.validate profile --label before` | hech narsa (Calculator ochiladi, ovoz 30% ga qo'yilib, keyin tiklanadi) | 3–5 daq |
| 7 | `python -m xadicha.validate abc` | boshlashga ruxsat; klaviaturaga tegmaysiz | 30–90 daq |
| 8 | `python -m xadicha.validate report` | — | 1 s |

Natijalar: `backend/validation/results/` (JSON va audio). Hisobot: `backend/validation/REPORT.md`.

## Ruxsatlar

Skriptlar macOS ruxsatlarini o'zi yoqmaydi va chetlab o'tmaydi. `env` qadami holatni so'rov oynasini chiqarmasdan
o'qiydi va nimani yoqish kerakligini aytadi:

- **Microphone** — System Settings → Privacy & Security → Microphone → Terminal.
- **Accessibility** — … → Accessibility → Terminal (yorqinlik tugmalari, klaviatura, accessibility daraxti).
- **Screen & System Audio Recording** — … → Terminal, so'ng Terminal'ni qayta oching (ekran surati, OCR).
- **Automation** — birinchi tekshiruvda macOS "Terminal Safari/Finder/Notes/System Events'ni boshqarmoqchi"
  deb so'raydi. Bu faqat mustaqil tekshiruv uchun (brauzer manzili, Finder tanlovi, Notes sarlavhasi) — OK bosing.

## Nimalar o'lchanadi

**Nutq (`speech`).** Ko'rilmagan to'plam: `backend/validation/speech_validation_set.csv` — 60 buyruq
(o'zbek lotin 14, o'zbek kirill 14, rus 12, ingliz 12, aralash 8) va 4 ta jimlik sinovi. U 127 buyruqli sozlash
korpusi va benchmark vazifalari bilan kesishmaydi (test tekshiradi). O'lchanadi: WER, CER, til aniqlash, niyat va
obyekt aniqligi, ASR vaqti, nutq tugashini sezish kechikishi (EOS), xato turlari: tushib qolgan so'z, noto'g'ri
qo'shimcha, til chalkashligi, ilova nomi xatosi, kesilish, jimlikda paydo bo'lgan matn. Har yozuv `.wav` bo'lib
saqlanadi; boshqa modellar bilan qayta baholash mumkin:

```bash
python -m xadicha.validate speech --rescore validation/results/speech-<vaqt> --models small,medium,large-v3-turbo --engines mlx,faster
```

Aralash tilli buyruqlarda "to'g'ri til" — buyruq fe'lining tili (javob shu tilda bo'lishi kerak).

**TTS (`tts`).** Faqat haqiqatan o'rnatilgan ovozlar: ilova tanlaydigan ovozlar, o'zbekka yaqin ovozlar
(turk, qozoq, ozarbayjon, qirg'iz) va `edge-tts` o'rnatilgan bo'lsa — uning o'zbek/rus/ingliz ovozlari. Iboralar:
`backend/validation/tts_pronunciation.csv` (o'zbekcha maxsus harflar, ismlar, rus, ingliz, texnik atamalar,
aralash). Har juftlik uchun dvigatel, aniq ovoz nomi, sintez vaqti, audio fayl va bahoingiz yoziladi.
`--all-voices` — barcha o'rnatilgan ovozlar.

**Avtomatlashtirish (`automation`).** 11 amal: Safari, Calculator, Finder, Notes, sayt, Google qidiruvi,
test papkasida papka yaratish, test faylini topish, uni Finder'da ko'rsatish, ekranni tasvirlash, Notes'da
sinov eslatmasi. Har biri agentning o'z da'vosidan **mustaqil** tekshiriladi (12-band). Faqat `~/XADICHA_TEST`
ishlatiladi; hech narsa o'chirilmaydi. `--voice` — buyruqni mikrofonga aytasiz (to'liq zanjir).

**Qidiruv (`search`).** 12 so'rov (uz/ru/en, umumiy, yangi ma'lumot, `site:` bilan, ma'nosiz so'rov). Tekshiruv:
natija bormi, manzillar ochiladimi, javobdagi iqtiboslar mavjud natijalarga ishora qiladimi, javobda to'qib
chiqarilgan manzil yo'qmi, leksik tayanch (taxminiy), `--judge` bilan — sizning bahoingiz.

**Tezlik (`profile`).** 4 buyruq × 3 takror (birinchisi "sovuq", alohida). Bosqichlar: VAD, ASR, til, niyat,
LLM, ekran surati, OCR, accessibility, bajarish, tekshiruv, TTS. Eng katta 3 ta tor joy chiqariladi.
Optimallashtirish faqat shundan keyin: o'zgarish → `profile --label after` → `profile --compare OLD NEW`.

**A/B/C (`abc`).** 12 ta xavfsiz vazifa × uz, ru, en × A, B, C (108 ishga tushirish). O'lchanadi: muvaffaqiyat
(mustaqil tekshiruv), vaqt, model chaqiruvlari soni, tekshiruv aniqligi, tiklanish. Xom log:
`backend/benchmark/results/run-*-REAL.jsonl`. Hisobot C ni faqat raqamlar shuni ko'rsatsa yaxshiroq deydi.

## Natijani menga yuborish

Har qadamdan keyin fayllar papkada qoladi. Claude ilovasida papka ulangan bo'lsa, "natijalarni tekshir" deb
yozing — natijalarni o'qib, tahlil qilib, tor joylarni optimallashtiraman.
