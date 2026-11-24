# macOS real qurilma tekshiruvi — protokol

Maqsad: simulyatsiyada tekshirib bo'lmaydigan narsalarni haqiqiy Mac'da tekshirish va natijani qayd etish.
Hech qanday buzuvchi amal bajarilmaydi. Har bir qadamdan oldin skript ruxsat so'raydi.

## Tayyorgarlik

```bash
cd ~/MAGISTRATURA/"XADICHA AI"/backend
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-macos-optional.txt   # OCR va accessibility uchun (ixtiyoriy)
```

**System Settings → Privacy & Security** da Terminal'ga (yoki backend ishlayotgan ilovaga): **Microphone**,
**Screen Recording**, **Accessibility**. Ruxsatdan keyin Terminal'ni qayta oching.

## 1. Avtomatlashtirilgan qo'lda tekshiruv

```bash
python scripts/mac_selftest.py
```

| Qadam | Nima qiladi | O'tdi mezoni |
|---|---|---|
| `permissions` | Accessibility ruxsatini tekshiradi | `accessibility: true` |
| `mic` | kirish qurilmasini aniqlaydi (yozmaydi) | qurilma nomi chiqadi |
| `speech` | uz/ru/en jumlani 5 s yozadi, matnga aylantiradi, WER/CER hisoblaydi | matn chiqadi; WER qayd etiladi |
| `tts` | uch tilda ovozli javob | foydalanuvchi eshitdi deb tasdiqlaydi |
| `screenshot` | ekran surati (saqlanmaydi) | rasm bo'sh emas; `scale` qayd etiladi |
| `ocr` | Apple Vision bilan matn o'qish | kamida 1 matn qutisi |
| `ax` | old plandagi ilova elementlari | kamida 1 element |
| `open_app` | Calculator'ni ochadi | old planda Calculator (`verified: true`) |
| `folder` | workspace ichida `xadicha-selftest-<vaqt>` papka | papka mavjud (o'chirilmaydi) |
| `type` | TextEdit'dagi bo'sh hujjatga `XADICHA test 123 — Salom, Салом, ўқғҳ` | foydalanuvchi to'liq ko'rdi |
| `stop` | faqat `wait` qadamli vazifani 1 s da to'xtatadi | `cancelled`, < 3 s |

Natija: `backend/data/selftest-<vaqt>.json` (OS, qurilma, CPU, Python, provayder, model, sozlamalar, har qadam).
Bitta qadamni qayta sinash: `python scripts/mac_selftest.py --only speech`.

## 2. Interfeys orqali qo'lda tekshiruv

Ikki Terminal: `python -m xadicha serve` va `npm run dev`, brauzerda http://localhost:3000.

1. **Ulanish** — chap pastda "Backend ulangan".
2. **Ovoz** — belgini bosing, "Safari ni och" deng, yana bosing. Kutiladi: animatsiya ovozga mos harakatlanadi; Safari ochiladi.
3. **Noaniq buyruq** — g'ayrioddiy talaffuz bilan ayting (yoki "open sufari" deb yozing va ovoz bilan takrorlang).
   Kutiladi: aniqlashtirish kartasi, eshitilgan matn, taklif; o'zicha hech narsa bajarilmaydi.
4. **Tasdiq** — "Desktopda \"Sinov\" papka yarat": dialog, qolgan soniyalar; "Yo'q" → bajarilmaydi; qayta "Ha" → papka yaratiladi.
5. **To'xtatish** — uzun vazifa paytida "To'xtatish": sarlavha "Kutish rejimi" ga qaytadi; panel "To'xtatildi".
6. **Holat mosligi** — vazifa tugagach sarlavha, panel va dashboard bir xil holatni ko'rsatadi.
7. **Til** — O'zbek / Русский / English; sahifani yangilang — til saqlanadi.
8. **Qayta ulanish** — backend'ni to'xtating (Ctrl+C) va qayta ishga tushiring: interfeys o'zi ulanadi.
9. **Ekran tahlili** — vision model bo'lsa "Ekranni tasvirlab ber"; javob ekranga mosligini baholang.

## 3. Qayd etish shabloni

```
Sana / vaqt:
macOS versiyasi:            Qurilma / chip:
Provayder / model:          STT dvigateli / model:
.env (CONFIRM_RISK, FAST_PATH, SCREEN_MAX_SIDE):
Buyruq yoki qadam:
Kutilgan natija:
Kuzatilgan natija:
Xato matni (bo'lsa):
Takrorlandi (necha marta / necha marta o'tdi):
```

Windows uchun alohida protokol hali yo'q — Windows'da sinalmagan.
