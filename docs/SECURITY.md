# Xavfsizlik

Qisqa xulosa: backend kompyuterni boshqaradi, shuning uchun u faqat shu kompyuterdagi interfeysga xizmat qiladi va
har bir xavfli harakat qatlamli tekshiruvdan o'tadi. Bu — tadqiqot prototipi; mustaqil xavfsizlik auditi o'tkazilmagan.

## Tahdid modeli

| Tahdid | Misol | Himoya |
|---|---|---|
| Begona sayt (CSRF) | ochiq tabdagi sayt `fetch("http://127.0.0.1:8765/api/stop")` | Origin tekshiruvi, sessiya kaliti (maxsus sarlavha → preflight), qat'iy CORS |
| DNS rebinding | `attacker.example` → 127.0.0.1 | `Host` sarlavhasi faqat `127.0.0.1`, `localhost`, `[::1]` |
| Begona WebSocket | sayt hodisalarni (buyruq matnlari) tinglaydi | WS'da Origin + Host + `?token=` tekshiruvi (CORS WS'ga qo'llanmaydi) |
| Tarmoqdan kirish | LAN'dagi qurilma | server faqat `127.0.0.1` ga bog'lanadi (`python -m xadicha serve`) |
| Model xatosi / prompt injection | ekrandagi matn "hammasini o'chir" deydi | model xavfni pasaytira olmaydi; taqiqlar tasdiqdan oldin; o'chirish har doim tasdiq |
| Yo'l aylanib o'tish | `/tmp/../etc`, symlink | yo'l `resolve()` qilingandan keyin tekshiriladi |
| Buyruq in'eksiyasi | ilova nomi `calc&whoami` | maxsus belgilar taqiqlangan; macOS `open -a` ro'yxat argumentlari bilan |
| Maxfiy ma'lumot sizishi | log'da API kalit | log filtri (`redact`), kalitlar `public()` da yo'q, `/docs` o'chirilgan |

Mahalliy zararli dastur (kompyuterda allaqachon ishlayotgan) — doiradan tashqarida: u kalitni o'qiy oladi.

## Nazoratlar (kod bo'yicha)

**Mahalliy API** — `backend/xadicha/api.py`
- `guard` middleware: Host → 400; begona Origin → 403; `/api/*` (`/api/session` dan tashqari) `X-Xadicha-Token`
  talab qiladi → 401 (`hmac.compare_digest`).
- Sessiya kaliti har ishga tushishda `secrets.token_urlsafe(32)`; diskka yozilmaydi; `/api/session` faqat Host/Origin
  tekshiruvidan o'tgan so'rovga, `Cache-Control: no-store` bilan.
- CORS: faqat `http(s)://localhost|127.0.0.1|[::1]:*`; ruxsat etilgan sarlavhalar: `content-type`, `x-xadicha-token`.
- Kiruvchi ma'lumot validatsiyasi: buyruq ≤ 2000 belgi, til `uz|ru|en`, `limit` 1..500, rejim `A|B|C`.
- OpenAPI/Swagger o'chirilgan.
- CORS — xavfsizlik chegarasi emas; asosiy himoya — Host + Origin + kalit.

**Harakatlar** — `backend/xadicha/safety.py`, `agent.py`
- Yakuniy xavf = max(qoida, model) — model pasaytira olmaydi.
- Tasdiq bilan ham bajarilmaydi: tizim papkalari (`/System`, `/usr`, `/etc`, `/private`, `/Library`, `/Applications`,
  `C:\Windows`, `C:\Program Files (x86)` …), `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`, `~/Library`, `AppData`,
  shell rc fayllari, uy papkasining o'zi va `~/Desktop`, `~/Documents` … ning o'zini o'chirish; `http/https`
  bo'lmagan URL; maxsus qobiq belgilari bor ilova nomi.
- `delete_path` — har doim `high`, faqat Savatga (Finder / send2trash).
- Tasdiq: aniq `True` bo'lsa bajariladi; rad, muddat (120 s), to'xtatish — bajarilmaydi; birinchi javob hisobga olinadi.

**Vositalar**
- Internet qidiruvi faqat `html.duckduckgo.com` va `{uz,ru,en}.wikipedia.org` ga; CAPTCHA va autentifikatsiya chetlab o'tilmaydi.
- Fayl qidiruvi faqat workspace ichida, sezgir papkalarsiz, faqat nom bo'yicha (tarkib o'qilmaydi).
- `reveal` faylni faqat Finder'da ko'rsatadi (`open -R`) — ochmaydi va ishga tushirmaydi.
- Suhbat xotirasi: maks. 20 navbat (xotirada), 200 (SQLite), `redact()`; ekran/OCR/clipboard saqlanmaydi.

**Klaviatura va clipboard** — `adapters/base.py`
- `type_text` clipboard orqali joylaydi (kirill uchun) va avvalgi clipboard tarkibini qaytaradi.
- `pyautogui.FAILSAFE`: sichqonchani ekranning yuqori-chap burchagiga olib borish — favqulodda to'xtatish.

**Maxfiylik**
- Ekran surati faqat xotirada; diskka yozilmaydi va logga chiqmaydi. Modelga yuboriladi: Ollama — lokal;
  Claude — Anthropic serveriga (foydalanuvchi `.env` da tanlagan bo'lsa).
- Vazifa tarixi (buyruq matnlari) lokal SQLite'da: `backend/data/xadicha.db`. Interfeysdan tozalash mumkin.
- Log: `backend/data/xadicha.log` — `RedactFilter` kalit, token, parol va base64 rasmlarni yashiradi.
- Benchmark brauzer tarixini o'qimaydi.

## Testlar

`backend/tests/test_security.py` (CSRF, DNS rebinding, WS, validatsiya, log), `test_regressions.py` (yo'l, URL, in'eksiya,
tasdiq), `test_state.py` (to'xtatish). Barchasi simulyatsiya (dry-run); haqiqiy hujum sinovi o'tkazilmagan.

## Qolgan xavflar

- Tasdiq dialogi ijtimoiy muhandislikdan himoya qilmaydi (foydalanuvchi "Ha" ni bosishi mumkin).
- `type_text` va `hotkey` kontekstga bog'liq: "yuborish" so'zi bo'lmasa o'rta xavf hisoblanadi.
- Claude provayderida ekran surati tashqi serverga ketadi — foydalanuvchi bilishi kerak.
- Windows adapteri umuman sinalmagan.
