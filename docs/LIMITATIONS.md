# Cheklovlar va rejadagi ishlar

## Sinalmagan (kod bor, real qurilmada tekshirilmagan)

- macOS adapteri: ilova ochish, AppleScript, Savatga o'tkazish, bosish koordinatalari (masshtab tuzatildi, lekin Retina'da sinalmagan).
- Mikrofon (sounddevice), STT (MLX / faster-whisper) — o'zbekcha aniqlik (WER) o'lchanmagan.
- TTS ovozlari (`say`, edge-tts).
- OCR (Apple Vision) va accessibility daraxti (AXUIElement) — MVP; pyobjc bilan real Mac'da ishga tushirilmagan.
- Ollama / Claude provayderlari bilan to'liq C sikli.
- Windows adapteri — umuman ishga tushirilmagan.

## Amalga oshirilmagan

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
