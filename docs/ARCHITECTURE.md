# Arxitektura

Bu hujjat **hozirgi kodni** tasvirlaydi. Rejadagi narsalar [LIMITATIONS.md](LIMITATIONS.md) da.

## Umumiy ko'rinish

```
Brauzer — Next.js (:3000)                         Python backend — FastAPI (:8765, faqat 127.0.0.1)
┌──────────────────────────────┐   HTTP + token   ┌─────────────────────────────────────────────┐
│ page.tsx + components/xadicha│ ───────────────▶ │ api.py   Host/Origin/token himoyasi          │
│ useXadicha (xadicha.ts)      │                  │ service.py  XadichaService                   │
│   └ state.ts  (yagona holat) │ ◀── WebSocket ── │   ├ agent.py      A / B / C rejimlari        │
│   └ events.ts (tekshiruv)    │   (seq, state)   │   ├ safety.py     xavf + taqiqlar            │
│ i18n.ts  uz / ru / en        │                  │   ├ understand.py niyat ishonchi, aniqlashtirish│
└──────────────────────────────┘                  │   ├ speech/       sounddevice + Whisper, TTS  │
                                                  │   ├ vision/       surat, OCR, accessibility   │
                                                  │   ├ adapters/     macOS / Windows / dry-run   │
                                                  │   └ storage.py    SQLite (tarix)              │
                                                  └─────────────────────────────────────────────┘
```

## Yagona holat modeli

- Backend — haqiqat manbai. `XadichaService.phase` = `idle | running | awaiting_confirmation | speaking`.
- Har bir hodisa `seq` (o'suvchi tartib raqami) oladi; `/api/status` ham `seq` va `instance` (jarayon id) qaytaradi.
- Holat o'zgarganda backend `state` hodisasini yuboradi: vazifa boshlanganda, tasdiq kutilganda, ovoz gapirganda va
  **vazifa to'liq tugagandan keyin** (oldingi xato: oxirgi e'lon yo'q edi, sarlavha "bajarilmoqda" holatida qolardi).
- Interfeys (`src/lib/state.ts`): `applyEvent` takroriy/eskirgan hodisani (`seq <= oxirgi`) e'tiborsiz qoldiradi;
  `applyStatus` eskirgan HTTP javobidan faqat statistika/sozlamalarni oladi; `instance` o'zgarsa (backend qayta
  ishga tushgan) yangi holat qabul qilinadi. Sarlavha, yordamchi, vazifa paneli va dashboard bitta `phase`/`busy` dan o'qiydi.
- Panelda `running` qolib, backend `idle` bo'lsa (`task_finished` yo'qolgan) — vazifa `/api/tasks/{id}` dan qayta olinadi.

## Marshrutlash (router.py)

```
buyruq → suhbat konteksti (havola: "uni", "shu fayl", "birinchisi", "yana") → til (lang.py)
      → fast        : ovoz/yorqinlik, ma'lum ilova, sayt, papka, "Google'da qidir" (brauzerda) — modelsiz
      → tool        : web_search (DuckDuckGo/Wikipedia → natijalar → model faqat shulardan qisqa javob)
                      find_file (workspace), reveal (Finder'da ko'rsatish)
      → autonomous  : LLM sikli (ekran + OCR/AX + suhbat konteksti) → qadam → tekshiruv → tiklanish
      → clarify     : obyekt yetishmaydi ("shu faylni top", kontekstda fayl yo'q) → savol
```

**Vositalar reyestri** (`models.TOOL_REGISTRY`): har harakat — `read_only`, `idempotent`, `timeout_s`, `verify`.
Adapter chaqiruvi vaqt chegarasi bilan; yiqilgan va takrorlab bo'lmaydigan harakatni (type_text, click, …) model aynan
qayta so'rasa — bajarilmaydi ("ko'r-ko'rona takrorlash" bloki). Model ixtiyoriy qobiq buyrug'i bera olmaydi.

**Suhbat konteksti** (`conversation.py`): chegaralangan (20 navbat), sessiyali, matnlar `redact()` dan o'tadi; ekran,
OCR yoki fayl tarkibi saqlanmaydi. SQLite `turns` jadvali — sessiyada maks. 200 navbat.

**Vaqt izi** (`TaskRecord.trace`): `audio_capture`, `vad_endpoint`, `asr`, `route`, `screen`, `llm:decide`,
`exec:<harakat>`, `tool:web_search`, `llm:summarize`, `tts` — ms, ok, provayder/model; matn tarkibisiz.

## Vazifa hayot sikli

```
POST /api/tasks → start_task (qulf, to'xtatish bayrog'i tozalanadi) → state(running)
  → agent.run: task_started → [qadam: blocked? → cancel? → tasdiq? → bajarish → step_finished] … → task_finished
  → TTS (state: speaking) → qulf bo'shaydi → state(idle)
```

- **To'xtatish**: `/api/stop` → agent bayrog'i, kutilayotgan tasdiq `cancelled`, TTS va yozuv to'xtaydi.
  `wait` qadami darhol uziladi. To'xtatishdan keyin yangi harakat bajarilmaydi (har qadam oldidan tekshiriladi;
  tasdiqlangandan keyin bosilgan to'xtatish ham hisobga olinadi). Bajarilayotgan bitta model so'rovini (HTTP) uzib
  bo'lmaydi — u tugagach, natijasi bajarilmaydi.

## Ovozli buyruq

```
sounddevice (backend, yagona yozuv) → mic_level hodisalari (vizualizatsiya)
  → Endpointer: fon shovqini → nutq → ~0.9 s jimlik = gapirib bo'lindi (avtomatik to'xtash)
  → Whisper (MLX yoki faster-whisper) → Transcript{text, language, asr_confidence}; jimlikdagi "uydirma" iboralar o'chiriladi
  → understand(): niyat, ilova nomi, intent_confidence, needs_clarification, suggestion
  → backend: aniq bo'lsa — darhol start_task; aks holda `clarify` hodisasi → interfeysda aniqlashtirish kartasi
```

Tizim buyruqlari (`system` harakati: ovoz, ovozsiz, yorqinlik) qoida tahlili bilan taniladi va fast path orqali
modelsiz bajariladi; xavf — past (tasdiq so'ralmaydi). macOS: AppleScript (ovoz qayta o'qib tekshiriladi), yorqinlik —
yorqinlik tugmalari (natijani o'qib bo'lmaydi). Model ham `system` harakatini ishlatishi mumkin; unga "faqat aytilganini
bajar, qo'shimcha harakat qilma" qoidasi berilgan. XADICHA hech qachon o'zicha vazifa boshlamaydi — faqat buyruq bilan.

- `asr_confidence` (Whisper segmentlari `avg_logprob`, `no_speech_prob`) va `intent_confidence` (matn tahlili) alohida.
- Hech qachon jim almashtirilmaydi: "Staffar in och" → taklif "Safari ni och", foydalanuvchi tanlaydi.
- Murakkab buyruqlar modelga topshiriladi (`delegated_to_model`); qoida rejimida esa aniqlashtirish so'raladi.

## Ekran konteksti

```
mss surat (to'liq piksel) → encode: mantiqiy o'lcham → ≤ SCREEN_MAX_SIDE JPEG (scale)
  ├ vision model: rasm (agar provayder ko'ra olsa)
  ├ OCR (Apple Vision, ixtiyoriy) → TextBox(x,y,w,h, confidence)
  └ Accessibility (AXUIElement, ixtiyoriy) → UIElement(role, name, x,y,w,h)
→ summarize(): matnli kontekst, koordinatalar rasm fazosida → model → click(x,y) → to_screen(x*scale) → adapter
```

`to_screen` — Retina va kichraytirishni hisobga oladi (oldingi xato: masshtab qo'llanmasdi).

## Rejimlar (tadqiqot)

| Rejim | Kirish | Reja | Tekshiruv |
|---|---|---|---|
| A | buyruq matni | qoida asosida, 1 harakat | yo'q |
| B | buyruq matni | LLM, bir martalik ko'p qadamli | yo'q |
| C | matn + ekran (+OCR/AX) | LLM, har qadamda | dasturiy + vizual, tiklanish |

Barcha rejimlar bir xil xavfsizlik qatlamidan o'tadi.
