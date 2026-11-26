# Gemini, nutq va real vaqt ovozi — arxitektura va qo'llanma

Bu hujjat XADICHA'ning bulut intellekti (Google Gemini), nutqni aniqlash (Gemini Transcribe + Whisper),
real vaqtli ovozli suhbat (Gemini Live), zaxira va oflayn rejim qanday ishlashini, qanday sozlanishini va
qanday tekshirilishini tushuntiradi. Har bir da'vo haqiqiy o'lchov, simulyatsiya testi yoki "hali sinalmagan"
deb aniq belgilangan.

## 1. Umumiy oqim

```
 Mikrofon ─► VAD (Endpointer) ─► STT ─────────────► Router ─► Agent ─► Action registry ─► macOS adapter
   │          (backend)          │ Gemini Transcribe   │         │ Gemini qaror (JSON,    (xavf, tasdiq,
   │                             │ yoki Whisper        │         │ ekran surati bilan)     allowlist)
   │                             ▼                     │         ▼
   │                     til aniqlash (uz/ru/en)       │   Ekran orqali tekshiruv → tiklanish
   │                                                   ▼
   │                                    Google Search grounding (alohida bosqich, faqat matn)
   │                                                   ▼
   │                                       Javob ─► TTS (edge / macOS say)
   │
   └─► Gemini Live (alohida quyi tizim): mikrofon 16 kHz PCM ⇄ WebSocket ⇄ model ovozi 24 kHz PCM
          desktop buyrug'i → `run_xadicha_command` → o'sha Agent (router + xavfsizlik + tasdiq)
```

| Qatlam | Fayl | Vazifasi |
|---|---|---|
| Gemini provayderi | `backend/xadicha/providers/gemini_provider.py` | `google-genai` SDK; JSON qarorlar, rasm, grounding, xato tasnifi, model zanjiri |
| Zaxira | `backend/xadicha/providers/fallback.py` | Gemini → Ollama; cooldown; faol provayderni halol ko'rsatish; oflayn rejim |
| STT | `backend/xadicha/speech/recognizer.py` | `auto / gemini / whisper`, lug'at va tuzatishlar, jimlikni yubormaslik, Whisper zaxirasi |
| Live | `backend/xadicha/speech/live.py` | Real vaqt WebSocket sessiyasi, barge-in, qayta ulanish, tool chaqiruvi |
| Sozlamalar | `backend/xadicha/settings.py` | Maxfiy bo'lmagan sozlamalar (`data/settings.json`), tekshiruv, darhol qo'llash |
| Redaksiya | `backend/xadicha/redaction.py` | Kalitlarni yashirish, subprocess muhitini tozalash |
| Interfeys | `src/components/xadicha/voice-intel.tsx`, `runtime-settings.tsx` | Provayder ko'rsatkichlari, Live, manbalar, Search Suggestions, sozlamalar |

## 2. Gemini — asosiy AI

* **SDK:** rasmiy `google-genai` (`requirements.txt`). Kalit faqat `backend/.env` dagi `GEMINI_API_KEY` dan o'qiladi,
  o'qilgandan keyin jarayon muhitidan olib tashlanadi.
* **Model:** `GEMINI_MODEL` (standart `gemini-3.8-flash` — 2026-11 holatiga rasmiy "Stable" ro'yxatida, yopilish sanasi
  e'lon qilinmagan). Kodga qotirilmagan: `.env` da almashtiriladi; `/api/status` modelning API'da mavjudligini
  `models.get` bilan tekshiradi (generatsiya xarajatisiz) va topilmasa aniq xabar beradi.
* **Model zanjiri:** `GEMINI_FALLBACK_MODELS` (standart `gemini-3.5-flash-lite`). Asosiy model 5xx / timeout / 404 /
  model limiti bersa, Ollama'dan oldin keyingi Gemini modeli sinaladi. 503 ("high demand") — bitta qisqa qayta urinish;
  504 va timeout — model 2–5 daqiqa chetlab o'tiladi. Kalit xatosida boshqa modellar sinalmaydi.
* **Javob formati:** agentning mavjud JSON formati (`Decision`, `Plan`) — `response_mime_type=application/json`,
  ekran surati `Part.from_bytes` bilan. Gemini faqat ruxsat etilgan harakatlarni *taklif* qiladi; ular registry,
  xavf darajasi, tasdiq va allowlist orqali o'tadi. Gemini hech qachon shell buyrug'ini bajarmaydi.

## 3. Internet qidiruvi — `XADICHA_SEARCH_MODE`

| Rejim | Xatti-harakat |
|---|---|
| `auto` | Faqat dolzarb yoki tashqi ma'lumot kerak bo'lsa (bugun, narx, kurs, yangilik, ob-havo, "eng so'nggi", yil…) va aniq "X haqida qidir" buyrug'ida |
| `always` | Har bir mos savolda (kichik suhbat — salom, rahmat, "sen kimsan" — bundan mustasno); modelga "qidiruvdan foydalan" deyiladi |
| `never` | Google qidiruvsiz; aniq qidiruv buyrug'i bepul DuckDuckGo/Wikipedia orqali |

* Grounding JSON qaror bosqichidan **alohida** chaqiriladi (`tools=[google_search]`, JSON rejimisiz) — vositalar
  aralashmaydi, harakat qaytarilmaydi.
* Manbalar, qidiruv so'rovlari, matn↔manba bog'lanishlari (`grounding_supports`) va **Google Search Suggestions**
  (`search_entry_point.rendered_content`) `task.data.grounding` orqali interfeysga o'zgarishsiz yetadi. Suggestions
  Google talabi bo'yicha javob bilan birga, skriptsiz izolyatsiyalangan `iframe` da ko'rsatiladi. Grounded matn
  o'zgartirilmaydi.
* **Grounding ishlamasa** (masalan, bepul tarifda `429 RESOURCE_EXHAUSTED`) — generatsiya to'xtamaydi; savolga mavjud
  bepul qidiruv natijalari va manbalari bilan javob beriladi, interfeysda "Google Search ishlamadi" deb ko'rsatiladi.

## 4. Nutqni aniqlash — `XADICHA_STT`

| Rejim | Xatti-harakat |
|---|---|
| `auto` | Gemini Transcribe (kalit bor va ishlayotgan bo'lsa), aks holda Whisper |
| `gemini` | Gemini Transcribe; ishlamasa Whisper — almashinuv `fallback_from/fallback_reason` da yoziladi |
| `whisper` | Faqat lokal Whisper (internetsiz) |

* Gemini Transcribe: `gemini-3.5-transcribe`, Interactions API (`client.interactions.create`), audio 16 kHz WAV
  xotirada (diskka yozilmaydi). Til avtomatik (code-switching), `custom_vocabulary` — 1000 tagacha atama.
* Haqiqatan ishlagan provayder har bir natijada: `transcript` hodisasi, vazifa izi (`asr` bosqichi), `/api/status → stt`.
  Interfeysda xabar ostida "UZ · Gemini" yoki "Gemini ishlamadi → Whisper".
* Jimlik yoki 0.25 s dan qisqa audio Gemini'ga yuborilmaydi. Gemini xato bersa, 30 s – 10 daqiqa (xato turiga qarab)
  Whisper ishlatiladi — takroriy keraksiz so'rov yo'q.
* **Lug'at:** `backend/vocabulary.json` (`vocabulary.example.json` dan nusxa) yoki Sozlamalar → Maxsus lug'at /
  Tuzatishlar. Tuzatishlar har ikkala provayder natijasiga so'z chegarasi bo'yicha qo'llanadi.

## 5. Gemini Live — real vaqtli suhbat

* Model `gemini-3.8-live` (`GEMINI_LIVE_MODEL`), `client.aio.live.connect` — haqiqiy ikki tomonlama WebSocket oqimi.
* Mikrofon 16 kHz 16-bit PCM (32 ms bo'laklar) → server VAD → model ovozi 24 kHz PCM → karnay.
* **Barge-in:** server `interrupted` yuborsa ijro navbati darhol tozalanadi.
* **Sessiya:** `session_resumption` handle, `go_away` da qayta ulanish, kontekst siqish (sliding window); tarmoq xatosida
  3 martagacha qayta ulanish (cheksiz emas), kalit xatosida darhol to'xtash.
* **Desktop buyruqlari:** model faqat `run_xadicha_command(instruction)` ni chaqira oladi → o'sha agent (router,
  xavfsizlik, tasdiq). Natija modelga qaytariladi — model "bajardim" deyishi uchun haqiqiy natija kerak.
* Live navbatlari suhbat kontekstiga yoziladi ("uni yana och" ishlaydi).
* **Cheklov:** macOS `sounddevice` oqimlarida aks-sado so'ndirish (AEC) yo'q — karnay ovozi mikrofonga tushsa,
  model o'zini to'xtatishi mumkin. **Quloqchin tavsiya etiladi.**
* Live mavjud bo'lmasa (kalit yo'q, `GEMINI_LIVE=0`, oflayn) — tugma o'chiq, sababi tooltip'da; oddiy ovoz yo'li ishlaydi.

## 6. Zaxira va oflayn rejim

| Ishlamay qolsa | Zaxira | Qanday ko'rinadi |
|---|---|---|
| Gemini modeli | keyingi Gemini modeli → Ollama (`OLLAMA_MODEL`) | `/api/status → provider.active/using_fallback/last_error`, interfeysda sariq "AI · Ollama (zaxira)" |
| Google Search grounding | DuckDuckGo/Wikipedia | Manbalar kartochkasida "Google Search ishlamadi" |
| Gemini Transcribe | Whisper (MLX yoki faster-whisper) | Xabar ostida "Gemini ishlamadi → Whisper", sozlamalarda sabab |
| Gemini Live | Oddiy ovoz yo'li (STT + TTS) | Live tugmasi o'chiq + sabab |
| Internet | Sozlamalar → Oflayn rejim: Ollama + Whisper | "oflayn" belgisi; bulut "ishlayapti" deb ko'rsatilmaydi |

Zaxiraga o'tishda vazifa va suhbat konteksti saqlanadi: Ollama'ga aynan bir xil system/user matn va ekran beriladi.

## 7. Sozlash

```bash
cd backend && source .venv/bin/activate
pip install -r requirements.txt          # google-genai shu yerda
cp .env.example .env                      # GEMINI_API_KEY ni yozing (faqat backend)
cp vocabulary.example.json vocabulary.json   # ixtiyoriy
```

Ish vaqtida (qayta ishga tushirmasdan) Sozlamalar → **Ishlash sozlamalari**: qidiruv rejimi, STT provayderi, Live,
ovozli javob, nutq tezligi, tilni avtomatik aniqlash, oflayn rejim, mikrofon, lug'at. Ular `backend/data/settings.json`
da saqlanadi (git'ga qo'shilmaydi). API kalitlari, provayder va model tanlovi — faqat `.env` (qayta ishga tushirish kerak).
`PUT /api/settings` noma'lum maydonni (masalan, `gemini_api_key`) **422** bilan rad etadi.

## 8. macOS ruxsatlari

| Ruxsat | Nima uchun | Qayerda |
|---|---|---|
| Mikrofon | Ovozli buyruq va Live | Tizim sozlamalari → Maxfiylik va xavfsizlik → Mikrofon → Terminal (yoki VS Code) |
| Ekran yozuvi | Ekran surati (C rejimi, ekran tahlili) | … → Ekran va tizim audio yozuvi |
| Accessibility | Bosish, yozish, accessibility daraxti | … → Accessibility |

Ruxsat Terminal/VS Code ilovasiga beriladi (backend shu ilova ichida ishlaydi). Ruxsatdan keyin ilovani qayta oching.

## 9. Diagnostika

```bash
curl -s localhost:8765/api/session                       # sessiya kaliti (faqat localhost)
# Holat (kalitsiz): provayder, faol model, zaxira, grounding, STT, Live
TOKEN=$(curl -s localhost:8765/api/session | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "x-xadicha-token: $TOKEN" localhost:8765/api/health | python3 -m json.tool
```

Haqiqiy API sinovlari (internet + kalit kerak; avtomatik testlar tarkibiga kirmaydi):

```bash
cd backend && source .venv/bin/activate
python scripts/gemini_smoke.py          # model, JSON, rasm, agent qarori, grounding, Ollama zaxirasi (kalit/tarmoq)
python scripts/gemini_live_smoke.py     # Live: uz/ru/en suhbat, tool chaqiruvi, barge-in (sintetik nutq)
python -m xadicha.validation.stt_compare               # STT: Gemini vs Whisper, bir xil audio
python -m xadicha.validation.stt_compare --limit 10    # tez
```

### Ovoz bo'yicha nosozliklar

| Belgisi | Sabab va yechim |
|---|---|
| "Mikrofon ochilmadi" | Mikrofon ruxsati yo'q yoki qurilma band — 8-bo'lim; Sozlamalar → Mikrofon'da boshqa qurilma tanlang |
| O'zbekcha nutq turkcha yoziladi | Whisper'ning ma'lum muammosi. `XADICHA_STT=auto/gemini` (Gemini Transcribe) yoki Live'da til cheklovi (uz/ru/en) qo'llanadi |
| Live o'zini o'zi to'xtatadi | Karnay ovozi mikrofonga tushmoqda (AEC yo'q) — quloqchin |
| Live tugmasi o'chiq | Tooltip'dagi sabab: kalit yo'q, `GEMINI_LIVE=0` yoki oflayn rejim |
| Sariq "AI · Ollama (zaxira)" | Gemini xatosi — Sozlamalar → AI bo'limida sabab va qayta sinash vaqti |
| "Google Search ishlamadi" | Ko'pincha bepul tarifda grounding kvotasi yo'q (429) — billing yoqing yoki `XADICHA_SEARCH_MODE=never` |
| Gemini 504 / 503 | Google tomonida yuklama; model zanjiri flash-lite'ga o'tadi, hammasi yiqilsa Ollama |

## 10. Xavfsizlik

* Kalit faqat backend'da: frontend kodi, API javoblari (`/api/status`, `/api/health`, `/api/settings`), loglar,
  traceback'lar va git'da yo'q (testlar va haqiqiy javoblar skaneri bilan tekshirilgan).
* Redaksiya: `sk-ant-…`, `AIza…`, URL'dagi `key=…`, `Bearer …`, `api_key=…` va konfiguratsiyadagi har qanday kalitning
  aynan qiymati — log yozuvlari, traceback, WebSocket `error` xabarlari, `grounding_error`.
* `open`, `osascript`, `say`, `mdfind` va boshqa subprocess'larga API kalitlarisiz muhit uzatiladi (`safe_env()`).
* Mavjud xavf darajalari, tasdiq, allowlist, taqiqlangan yo'llar, maksimal qadamlar va favqulodda to'xtatish o'zgarmagan;
  Live buyruqlari ham shulardan o'tadi.
