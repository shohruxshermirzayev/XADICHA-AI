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

## 3. WebSocket

- Server har bir ulanishda `hello` (to'liq `status`) yuboradi, keyin hodisalarni uzatadi.
- Server mijoz xabarlarini o'qiydi: `{"type":"ping"}` → `{"type":"pong"}`; noto'g'ri JSON va noma'lum xabarlar e'tiborsiz qoldiriladi.
  Mijoz uzilganda obuna darhol tozalanadi (avval keyingi hodisagacha osilib qolardi).
- Sekin mijoz: navbat 1000 hodisa bilan cheklangan; to'lganda faqat `mic_level` tashlab yuboriladi.
- Interfeys (`src/lib/xadicha.ts`, `src/lib/events.ts`):
  - har bir xabar `parseEvent` orqali tekshiriladi — noto'g'ri xabar ilovani yiqitmaydi;
  - bir vaqtda faqat bitta ulanish; eski ulanish hodisalari e'tiborsiz;
  - qayta ulanish: 1 s, 2 s, 4 s … 30 s gacha (±20%); HTTP polling backend qaytganini sezsa — darhol ulanadi;
  - polling faqat WebSocket yo'q paytda ishlaydi; WebSocket hodisasidan oldin boshlangan HTTP javobi tasdiq/tinglash
    holatini bosib qo'ymaydi ("davr" hisoblagichi);
  - qayta ulanganda joriy vazifa `/api/tasks/{id}` dan tiklanadi va uzilish paytida tugagan vazifa javobi chatga bir marta qo'shiladi.

## 4. Mikrofon

- Mikrofonni **faqat backend** ochadi (`sounddevice`, 16 kHz mono). Avval brauzer ham `getUserMedia` bilan
  vizualizatsiya uchun alohida ochardi — bu ikki marta yozish va qo'shimcha ruxsat oynasi edi; olib tashlandi.
- Ovoz balandligi: `mic_level` hodisasi (~15 Hz, RMS asosida 0..1). Animatsiya haqiqiy yozuvga bog'langan.
- Holat: `listening` hodisasi va `status.listening` (`idle | recording | transcribing`). Interfeys HTTP javobidan ham
  holatni yangilaydi — WebSocket uzilgan bo'lsa ham tugma haqiqiy holatni ko'rsatadi.
- Xatolar: `error` hodisasi (`code: "microphone"`) va `POST /api/listen/stop` → `503` tushunarli matn bilan
  (mikrofon topilmadi / ruxsat yo'q / PortAudio). `stop` siz `listen/stop` → `409`. Vazifa bajarilayotganda `listen/start` → `409`.
- Favqulodda to'xtatish yozuvni matnga aylantirmasdan bekor qiladi.

## 5. Xavfsizlik

`backend/xadicha/safety.py`:

| Tekshiruv | Natija |
|---|---|
| `delete_path` | har doim `high` (tasdiq) |
| fayl amali workspace tashqarisida | `high` |
| tizim papkalari (yechilgan yo'l bo'yicha), `C:\Program Files (x86)` | **taqiqlangan** |
| `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`, `~/Library`, `AppData`, shell rc fayllar | **taqiqlangan** |
| uy papkasi, `~/Desktop`, `~/Documents` … ning o'zini o'chirish | **taqiqlangan** (ichidagi fayl — tasdiq bilan) |
| `open_url`: `http/https` — `low`; `mailto/tel` — `medium`; boshqa sxema yoki yo'l | **taqiqlangan** |
| `open_app` nomida `& | < > ^ % " \` $ ;` yoki `-` bilan boshlanadi | **taqiqlangan** |
| Terminal, System Settings, Keychain … ochish | `high` |
| yuborish/o'rnatish/to'lov/o'chirish so'zlari (uz/ru/en) | `high` |

Taqiqlangan harakat tasdiq so'ralmasdan rad etiladi. Adapterlarda ham ikkinchi himoya bor (URL sxemasi, ilova nomi).

## 6. Ekran tushunish — nima bor, nima yo'q

| Imkoniyat | Holat |
|---|---|
| Ekran surati (mss) → vision modelga (Claude yoki Ollama vision) | ✅ amalga oshirilgan; sifati modelga bog'liq |
| Koordinatalarni mantiqiy nuqtalarga moslash (Retina) | ✅ birlik test |
| OCR (matnni aniq tanib olish) | ❌ yo'q |
| Accessibility daraxti (AXUIElement / UI Automation) | ❌ yo'q |
| Dasturiy tekshiruv: ilova old planda, fayl/papka mavjud | ✅ adapterlarda (real qurilmada sinalmagan) |

`/api/status.capabilities` = `{screenshot_vision, ocr: false, accessibility_tree: false}`; interfeys shuni ko'rsatadi.
Qoida asosidagi (`mock`) model ekranni ko'rmaydi.

## 7. Tillar

- Interfeys: `src/lib/i18n.ts` — o'zbek, rus, ingliz; barcha kalitlar uch tilda bir xil (test bilan tekshiriladi).
  Tanlangan til `localStorage` (`xadicha.lang`) da saqlanadi; saqlash taqiqlangan bo'lsa ham sessiya ichida almashadi.
- Yozilgan buyruq tili: lotin — tanlangan til; kirill — `ў қ ғ ҳ` yoki o'zbekcha so'zlar bo'lsa `uz`, aks holda `ru`.
- Qoida asosidagi tahlil o'zbek kirill buyruqlarini ham tushunadi ("Сафари ни оч", "папка яратинг").
- Cheklov: backend xato matnlari (`HTTPException.detail`) hozircha faqat o'zbekcha.

## 8. Testlar

| Buyruq | Nima tekshiriladi |
|---|---|
| `cd backend && python -m pytest -q` | agent, xavfsizlik, API, WebSocket, tasdiq, mikrofon holati (soxta), kirill tahlili |
| `npm test` | tarjimalar to'liqligi, til aniqlash, WebSocket xabarlarini tekshirish, qayta ulanish kechikishi |
| `npm run lint`, `npm run typecheck`, `npm run build` | statik tekshiruv va build |

Barcha backend testlari `DryRunAdapter` va soxta model bilan ishlaydi.

## 9. Real qurilmada sinash kerak bo'lganlar

macOS (Apple Silicon):
- `open -a`, AppleScript bilan old plandagi ilovani aniqlash, Finder orqali Savatga o'tkazish;
- Accessibility / Screen Recording / Microphone ruxsatlari va ular berilmaganda chiqadigan xabarlar;
- Retina'da bosish koordinatalari; `pyautogui` FAILSAFE (yuqori-chap burchak);
- `sounddevice` bilan haqiqiy yozuv, `mic_level` animatsiyasi, MLX Whisper tezligi va o'zbekcha aniqlik;
- clipboard orqali kirill/o'zbek matnini yozish.

Windows:
- butun adapter (`cmd /c start`, `webbrowser`, `send2trash`, oyna sarlavhasi orqali tekshiruv) — hali hech qachon ishga tushirilmagan;
- `pyttsx3` ovozlari, `Ctrl` tugma xaritasi, `C:\` yo'llari bilan xavfsizlik qoidalari.

Model:
- Ollama `qwen3.5:9b` va Claude bilan C rejimining haqiqiy TSR, kechikish va tiklanish ko'rsatkichlari.
