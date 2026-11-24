# XADICHA AI — texnik hujjat

Bu hujjat **hozirgi** amalga oshirilgan holatni tasvirlaydi. Rejadagi narsalar alohida belgilangan.

## 1. Arxitektura

```
Brauzer (Next.js, :3000)  ──HTTP──▶  FastAPI (:8765)  ──▶  XadichaService
        ▲                                   │                 ├── Agent (A/B/C rejimlari)
        └────────────WebSocket /api/ws ◀────┘                 ├── safety (xavf + taqiqlar)
                                                              ├── OS adapter (macOS / Windows / dry-run)
                                                              ├── Listener (sounddevice + Whisper)
                                                              └── Storage (SQLite)
```

Backend — yagona haqiqat manbai. Interfeys holatni WebSocket hodisalaridan oladi, uzilishda esa HTTP orqali tiklaydi.
Batafsil: [ARCHITECTURE.md](ARCHITECTURE.md) (holat modeli, vazifa sikli, ovoz va ekran quvurlari),
[SECURITY.md](SECURITY.md), [TESTING.md](TESTING.md), [MACOS_TEST_PROTOCOL.md](MACOS_TEST_PROTOCOL.md),
[RESEARCH_METHODOLOGY.md](RESEARCH_METHODOLOGY.md), [LIMITATIONS.md](LIMITATIONS.md).

## 2. Tasdiq protokoli

1. Agent xavfi `CONFIRM_RISK` dan past bo'lmagan harakatga duch keladi → `confirm_request` hodisasi
   (`id`, `task_id`, `description`, `risk`, `reason`, `expires_at`). `/api/status` ham `pending_confirmation` ni qaytaradi.
2. Interfeys `POST /api/tasks/{task_id}/confirm` `{approve, confirmation_id}` yuboradi.
   - `200` — qabul qilindi; `404` — kutilayotgan tasdiq yo'q (muddati tugagan, to'xtatilgan yoki eski `confirmation_id`);
     `409` — allaqachon javob berilgan. Faqat **birinchi** javob hisobga olinadi.
3. Natija `confirm_resolved` hodisasida: `outcome` = `approved | denied | timeout | cancelled`.
4. Agent faqat aniq `True` bo'lsa bajaradi. Tasdiqlangandan keyin to'xtatish bosilgan bo'lsa ham bajarilmaydi.

Interfeys: so'rov ketayotganda tugmalar o'chiriladi (takroriy yuborish yo'q); tarmoq xatosida dialog **ochiq qoladi** va
xato ko'rsatiladi; `404/409` da dialog yopiladi va chatda sababi yoziladi; qolgan soniyalar ko'rsatiladi.
Sahifa yangilansa, kutilayotgan tasdiq `hello`/`status` orqali qayta ochiladi.

Muddat: `XadichaService(confirm_timeout=120)` (soniya).

## 3. WebSocket va yagona holat

- Ulanish: `ws://127.0.0.1:8765/api/ws?token=<sessiya kaliti>`; Origin va Host tekshiriladi (aks holda 4401 bilan yopiladi).
- Server har ulanishda `hello` (to'liq `status`, `seq`, `instance`) yuboradi, keyin har bir hodisa `seq` bilan.
- `state` hodisasi: `{busy, phase, current_task, listening}` — vazifa boshlanganda, tasdiq kutilganda, gapirganda va
  vazifa to'liq tugagach. Interfeysdagi barcha "band" belgilari faqat shundan o'qiladi (`src/lib/state.ts`).
- Mijoz `{"type":"ping"}` → `pong`; noto'g'ri JSON/noma'lum xabar e'tiborsiz; uzilishda obuna darhol tozalanadi.
- Sekin mijoz: navbat 1000 hodisa; to'lsa faqat `mic_level` tashlanadi.
- Interfeys: `parseEvent` bilan tekshiruv; bitta ulanish; qayta ulanish 1→30 s (±20%), HTTP polling backend
  qaytganini sezsa darhol ulanadi; polling faqat WebSocket yo'q paytda; eskirgan HTTP javobi (`seq` kichik)
  band/tasdiq/tinglash holatini bosmaydi; `instance` o'zgarsa (backend qayta ishga tushgan) holat qabul qilinadi.

## 4. Mikrofon

- Mikrofonni **faqat backend** ochadi (`sounddevice`, 16 kHz mono). Avval brauzer ham `getUserMedia` bilan
  vizualizatsiya uchun alohida ochardi — bu ikki marta yozish va qo'shimcha ruxsat oynasi edi; olib tashlandi.
- Ovoz balandligi: `mic_level` hodisasi (~15 Hz, RMS asosida 0..1). Animatsiya haqiqiy yozuvga bog'langan.
- Holat: `listening` hodisasi va `status.listening` (`idle | recording | transcribing`). Interfeys HTTP javobidan ham
  holatni yangilaydi — WebSocket uzilgan bo'lsa ham tugma haqiqiy holatni ko'rsatadi.
- Xatolar: `error` hodisasi (`code: "microphone"`) va `POST /api/listen/stop` → `503` tushunarli matn bilan
  (mikrofon topilmadi / ruxsat yo'q / PortAudio). `stop` siz `listen/stop` → `409`. Vazifa bajarilayotganda `listen/start` → `409`.
- Favqulodda to'xtatish yozuvni matnga aylantirmasdan bekor qiladi.
- Avtomatik rejim (`POST /api/listen/start?auto=true&mode=C`, interfeys standarti): `Endpointer` gapirib bo'linganini
  sezadi, backend matnni tahlil qiladi va aniq buyruqni darhol bajaradi (`voice_result: started`); noaniq bo'lsa —
  `clarify` hodisasi (hech narsa bajarilmaydi); bo'sh yoki "uydirma" matn — `voice_result: empty`.
  Erta to'xtatish (`/api/listen/stop`) ham shu yo'ldan o'tadi (`handled: true`).

## 5. Xavfsizlik

To'liq tavsif: [SECURITY.md](SECURITY.md). Qisqacha: Host/Origin/sessiya kaliti himoyasi, harakat taqiqlari
(yechilgan yo'l bo'yicha), model xavfni pasaytira olmaydi, o'chirish faqat tasdiq bilan va Savatga, log redaksiyasi.

## 6. Ekran tushunish — nima bor, nima yo'q

| Imkoniyat | Holat |
|---|---|
| Ekran surati (mss) → vision model | ✅ yozilgan; real Mac'da sinalmagan; sifati modelga bog'liq |
| Koordinatalarni ekran nuqtalariga o'tkazish (`to_screen`, Retina) | ✅ tuzatildi (avval masshtab qo'llanmasdi); birlik test |
| OCR — Apple Vision (`vision/context.py`) | ⚠️ ixtiyoriy MVP (`requirements-macos-optional.txt`); real Mac'da sinalmagan |
| Accessibility daraxti — AXUIElement (`vision/context.py`) | ⚠️ ixtiyoriy MVP; soxta daraxt bilan testlangan; real Mac'da sinalmagan |
| Windows OCR / UI Automation | ❌ amalga oshirilmagan |

OCR va accessibility natijasi modelga **matnli kontekst** sifatida beriladi (koordinatalar rasm fazosida); vision'siz
model ham undan foydalanadi. `/api/status.capabilities` har bir imkoniyat uchun `available | unavailable | not_tested |
not_implemented` holatini va izohini qaytaradi; sozlama mavjudligi "yoqilgan" degani emas.

## 7. Tillar va nutq ishonchi

- Interfeys: `src/lib/i18n.ts` — o'zbek, rus, ingliz; kalitlar uch tilda bir xil (test). Tanlov `localStorage` da.
- Yozilgan buyruq tili: lotin — tanlangan til; kirill — `ў қ ғ ҳ` yoki o'zbekcha so'zlar bo'lsa `uz`, aks holda `ru`.
- Ovozli buyruq: `asr_confidence` (Whisper segmentlari) va `intent_confidence` (`understand.py`) alohida.
  Aniqlashtirish kerak bo'lganda (`low_asr_confidence`, `unknown_app`, `normalized_particle`, `unknown_intent`)
  interfeys eshitilgan matnni ko'rsatadi; buyruq faqat foydalanuvchi tanlagach bajariladi. `POST /api/understand` — tahlil, bajarmasdan.
- Aralash til: "открой Telegramni", "open Telegram ni" — qo'llab-quvvatlanadi. Aniqlik o'lchanmagan.
- Cheklov: backend xato matnlari faqat o'zbekcha.

## 8. Testlar

[TESTING.md](TESTING.md) — buyruqlar, fayllar xaritasi, simulyatsiya va real qurilma farqi.

## 9. Real qurilmada sinash

[MACOS_TEST_PROTOCOL.md](MACOS_TEST_PROTOCOL.md) va `backend/scripts/mac_selftest.py`. Windows — hali sinalmagan.
