# Cheklovlar va rejadagi ishlar

## Sinalmagan (kod bor, real qurilmada tekshirilmagan)

- macOS adapteri: ilova ochish, AppleScript, Savatga o'tkazish, bosish koordinatalari (masshtab tuzatildi, lekin Retina'da sinalmagan).
- Mikrofon (sounddevice), STT (MLX / faster-whisper) — o'zbekcha aniqlik (WER) o'lchanmagan.
- TTS ovozlari (`say`, edge-tts).
- OCR (Apple Vision) va accessibility daraxti (AXUIElement) — MVP; pyobjc bilan real Mac'da ishga tushirilmagan.
- Ollama / Claude provayderlari bilan to'liq C sikli.
- Windows adapteri — umuman ishga tushirilmagan.

- Gapirib bo'linganini sezish (`Endpointer`) chegaralari real mikrofon va shovqinli xonada sozlanmagan.
- Ovoz/yorqinlik boshqaruvi: macOS'da sinalmagan; yorqinlik tugmalari tashqi monitorda ishlamasligi mumkin va
  natijasini dasturiy tekshirib bo'lmaydi. Windows'da ovoz — multimedia tugmalari, yorqinlik — WMI (sinalmagan).

- Internet qidiruvi (DuckDuckGo HTML — rasmiy API emas, sahifa tuzilishi o'zgarishi yoki CAPTCHA so'rashi mumkin;
  Wikipedia — zaxira) real tarmoqda sinalmagan.
- `lang.py`, `router.py`, `understand.py` — qoida asosida; 127 buyruqli korpusda 100% (lekin xatolar AYNAN shu korpusda
  topilib tuzatilgan — bu regressiya testi, umumlashtirish aniqligi emas; tuzatishdan oldin: LID 92.1%, niyat 96.9%).
- macOS `say` da o'zbek ovozi yo'q: o'zbekcha javob faqat `TTS_ENGINE=edge` bilan aytiladi (internet kerak); boshqa
  tildagi ovoz bilan o'qitilmaydi. Talaffuz tinglash testidan o'tmagan.

## Amalga oshirilmagan

- Javoblarni oqim (streaming) bilan chiqarish va gap-gap TTS (hozir — to'liq javob, "o'ylayapman" ko'rsatkichi).
- Brauzerda DOM orqali boshqarish (Playwright) — brauzer vazifalari hozir open_url + ekran/koordinata.
- Accessibility elementini to'g'ridan-to'g'ri bosish (AX daraxti faqat modelga matnli kontekst).
- Mustaqil o'qish amallarini parallel bajarish (bog'liqlik grafigi) — hozir ketma-ket.
- Ekran o'zgarmaganda suratni qayta olmaslik (har LLM qadamida yangi surat).

- Windows OCR va UI Automation.
- Accessibility daraxti orqali to'g'ridan-to'g'ri element bosish (hozir faqat matnli kontekst modelga beriladi).
- Ovozli aniqlashtirish (karta faqat ekranda; ovoz bilan "ha/yo'q" javobi yo'q).
- Real benchmark natijalari va nutq WER o'lchovlari.
- Yordamchi texnologiyalar (VoiceOver) bilan sinov va foydalanuvchi tadqiqoti.
- Backend xato matnlarining rus/ingliz tarjimasi (hozir faqat o'zbekcha).

## Ma'lum cheklovlar

- Bajarilayotgan bitta model so'rovini to'xtatish uzmaydi; javob kelgach, harakat bajarilmaydi.
- `understand.py` — qoida va o'xshashlik asosida; ilova ro'yxati cheklangan; ro'yxatda yo'q ilova past ishonch bilan ochiladi.
- Apple Vision o'zbek tilini alohida qo'llab-quvvatlamaydi (lotin — ingliz, kirill — rus modeli bilan).
- Ekran surati faqat asosiy monitordan.
- Interfeys mahalliy foydalanish uchun; masofadan kirish nazarda tutilmagan.
- Hech bir qism "production-ready" emas.
