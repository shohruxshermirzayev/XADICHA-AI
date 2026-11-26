# Stage 1 — ovoz va ko'p tilli tushunish (2026-11-26)

Dalil belgilari: **[T]** avtomatik test (simulyatsiya), **[A]** haqiqiy API, **[M]** real mikrofon, **[H]** inson nutqi.

## Bajarildi

| Ish | Natija | Dalil |
|---|---|---|
| **B1** — oraliq matn buyruq sifatida bajarilmaydi | Transkripsiya holati: `final` (server yakuniy matni) yoki `local` (kutish oralig'ida yakuniy matn kelmadi — oraliq matn mahalliy yakunlandi). `local` hech qachon o'zicha bajarilmaydi: interfeysda "Gapingiz oxirigacha tasdiqlanmadi — shu buyruqni bajaraymi?" (bajarish / tahrirlash / bekor qilish). Yakunlanish sababi (`finalize_reason`) hodisa va vazifa izida | [T] `test_locally_finalized_transcript_is_never_executed_but_clarified` |
| Yakuniy matnni kutish | 1.2 s → 2.0 s (o'lchov: jimlik oqimi bilan server yakuniy matni 0.64–0.92 s; endi `local` holati kamroq) | [A] avvalgi o'lchovlar |
| **B2** — Live aks-sado himoyasi | Standart: XADICHA gapirayotganda (va 0.35 s keyin) mikrofon jimlik bilan almashtiriladi — karnay ovozi modelni to'xtatmaydi; oqim uzilmaydi. Sozlamalar → "Live: gapini bo'lish (quloqchin bilan)" yoqilsa — barge-in | [T] 3 test |
| **B4** — o'zbek yozuvi afzalligi | Nutqda yozuv yo'q: STT lotinda beradi. Sozlamalar → "O'zbekcha yozuv: Kirill" tanlansa, transkripsiya kirillga o'giriladi; ilova/brend nomlari (VS Code, Safari, Google Chrome) lotinda qoladi; marshrut o'zgarmaydi | [T] 8 test |
| Inson nutqi baholash vositasi | `validate speech`: `--set dev|heldout|regression`, `--providers whisper,gemini,gemini-live` (bir xil yozuvda), aniq rozilik, metadata (taxallus, muhit, tezlik, mikrofon), JSON + CSV, xato sababi yoziladi | [T] 6 test; [A] dev to'plamida 3/3 to'g'ri (sintetik ovoz — vositani tekshirish uchun) |
| Yangi to'plamlar | `human_dev.csv` (24, sozlash uchun), `human_heldout_v2.csv` (47, **ko'rilmagan**: dev va eski to'plam bilan kesishmaydi; uz lotin/kirill, ru, en, aralash, jimlik). Eski `speech_validation_set.csv` sintetik benchmark'larda ishlatilgani uchun endi **regressiya** to'plami | [T] |

Ko'rilmagan to'plam bu bosqichda tizimni sozlash uchun ishga tushirilmadi (faqat format tekshirildi).

## Bajarilmadi (sabab bilan)

| Ish | Sabab / keyingi qadam |
|---|---|
| Inson nutqi bilan WER/CER/intent/entity | Sizning (va boshqa ishtirokchilarning) roziligi bilan yozuv kerak — buyruqlar quyida |
| Shovqinli muhit, turli tezlik va aksentlar | Yozuv sessiyalari `--env noisy`, `--speed fast/slow`, turli `--speaker` bilan |
| B3 — oqimli ulanish xatolari (9/68) | Ilovada bufer zaxira STT'ga beriladi (buyruq yo'qolmaydi); pool sessiyasi yiqilganda yangi ulanish bilan qayta urinish — Stage 2 (provayder ishonchliligi) |
| Ishonch asosidagi aniqlashtirish (Gemini) | Gemini so'z darajasidagi ishonch bermaydi; hozircha holat (`local`) va tushunish tahlili (`understand`) ishlatiladi |
| B6/B7 muhit xatolari (PyAV, mlx-whisper) | Kodda chetlab o'tilgan (`wave` bilan o'qish); `pip install -r requirements.txt` + model yuklash — foydalanuvchi qarori |

## Inson nutqi yozuvi (rozilik bilan)

```bash
cd backend && source .venv/bin/activate
# 1) Ko'rilmagan to'plam — tinch xona, oddiy tezlik
python -m xadicha.validate speech --set heldout --speaker s01 --env quiet --speed normal
# 2) Shovqinli muhit / tez nutq (alohida sessiyalar)
python -m xadicha.validate speech --set heldout --speaker s01 --env noisy
python -m xadicha.validate speech --set heldout --speaker s01 --speed fast
# 3) Bir xil yozuvlarni uchala STT bilan solishtirish
python -m xadicha.validate speech --rescore validation/results/speech-<vaqt> --providers whisper,gemini,gemini-live
```

Yozuvlar faqat shu kompyuterda (`backend/validation/results/…/audio/`, git'ga qo'shilmaydi). Gemini bilan
baholashda audio Google'ga yuboriladi — rozilik matnida aytiladi. Ism o'rniga taxallus (`s01`) ishlatiladi.

## Testlar

Backend 609 (Stage 0 da 589), interfeys 41, TypeScript, ESLint, build — o'tdi.

## Xavflar va keyingi bosqich

- `local` holati ko'p bo'lsa, foydalanuvchi tez-tez tasdiqlashi kerak bo'ladi — inson nutqi yozuvlarida o'lchanadi.
- Kirill o'girish qoidalari asosiy qoidalarni qamraydi; kam uchraydigan so'zlar (ruscha o'zlashmalar) noto'g'ri
  o'girilishi mumkin — faqat ko'rsatish uchun, marshrutga ta'sir qilmaydi (test bilan tekshirilgan).
- **Stage 2** — provayder router: Claude (murakkab reja), sog'liq monitoringi, kvota/narx/kechikish kuzatuvi,
  tanlash UI'si, B3 (oqim qayta ulanishi).
