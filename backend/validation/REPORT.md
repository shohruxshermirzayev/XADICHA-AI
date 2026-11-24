# XADICHA AI — real MacBook validatsiyasi hisoboti

Yaratildi: 2026-11-24 15:17 · natija fayllari: 1 ta · papka: `backend/validation/results/`.

Hisobot faqat saqlangan real o'lchovlardan avtomatik tuzilgan. Simulyatsiya yoki o'tkazilmagan sinov — **NOT TESTED**. Avtomatik testlar (pytest, e2e) bu yerda real natija sifatida hisoblanmaydi.

## 1. Mac muhiti

**NOT TESTED**

## 2. Real nutq sinovi

Real mikrofon sinovi: **NOT TESTED**

Qo'shimcha (real nutq EMAS): ko'rilmagan to'plam matni, ASR'siz — til 100.0%, niyat 90.0%, obyekt 86.7% (`speech_text-20261124-151519.json`).

## 3. Real TTS

**NOT TESTED**

## 4. Real internet qidiruvi

**NOT TESTED**

## 5. Real macOS avtomatlashtirish

**NOT TESTED**

## 6. Kechikish taqsimoti

**NOT TESTED**

## 7. Oldin / keyin

**NOT TESTED** (optimallashtirish real o'lchovdan keyin qilinadi: `profile --label before`, o'zgarish, `profile --label after`, `profile --compare`)

## 8. A/B/C taqqoslash

**NOT TESTED**

## 9. Yiqilgan sinovlar

Real natijalarda yiqilgan sinov yo'q (yoki sinovlar o'tkazilmagan).

## 10. Qolgan cheklovlar

- Windows: real Windows kompyuterda sinalmagan — NOT TESTED.
- Bitta foydalanuvchi va bitta qurilmada o'lchangan; ovoz, aksent va mikrofon xilma-xilligi qamrab olinmagan.
- TTS baholari bitta tinglovchidan (sub'ektiv); MOS uchun bir nechta baholovchi kerak.
- Qidiruv natijalari vaqtga bog'liq — qayta ishga tushirilganda boshqacha bo'lishi mumkin.
- Ko'rilmagan nutq to'plamini muallif yozgan; u tizimni sozlashda ishlatilmagan, lekin muallif xolisligi istisno emas.

## 11. Siz bajarishingiz kerak bo'lgan qadamlar

1. `python -m xadicha.validate env` ni ishga tushiring (env: hali **NOT TESTED**).
2. `python -m xadicha.validate speech` ni ishga tushiring (speech: hali **NOT TESTED**).
3. `python -m xadicha.validate tts` ni ishga tushiring (tts: hali **NOT TESTED**).
4. `python -m xadicha.validate automation` ni ishga tushiring (automation: hali **NOT TESTED**).
5. `python -m xadicha.validate search --judge` ni ishga tushiring (search: hali **NOT TESTED**).
6. `python -m xadicha.validate profile --label before` ni ishga tushiring (profile: hali **NOT TESTED**).
7. `python -m xadicha.validate abc` ni ishga tushiring (abc: hali **NOT TESTED**).
8. Optimallashtirishdan keyin: `python -m xadicha.validate profile --label after` va `--compare`.
9. Windows: real Windows kompyuterda sinov (hozircha imkoni yo'q) — NOT TESTED.
