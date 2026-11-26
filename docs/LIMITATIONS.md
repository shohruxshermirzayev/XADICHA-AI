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

## Ko'rilmagan to'plamda topilgan zaif joylar (matn, ASR'siz)

`python -m xadicha.validate speech --text-only` — 60 ta yangi buyruq (sozlashda ishlatilmagan): til aniqlash 100%,
niyat 90,0%, obyekt 86,7%. Bu real nutq natijasi emas (ASR yo'q) — tushunish qatlamining yuqori chegarasi.
Tezkor yo'l tanimagan buyruqlar modelga (LLM) o'tadi, lekin model yo'q yoki sekin bo'lsa bu sezilarli:

- ingliz: "Make it quieter", "Dim the screen", "Find the contract file" — tezkor yo'lda tanilmaydi;
- rus: "Сделай потише", "Сделай громче, iltimos", "Открой Telegram, iltimos" — tanilmaydi;
- aralash: "Calculatorni open qil" — ilova nomi noto'g'ri ("Qil") olinadi, ochish yiqiladi, keyin modelga o'tadi.

To'plam ataylab tuzatilmadi: real nutq sinovi ham shu to'plamda o'tkaziladi. Tuzatishdan keyin u regressiya
to'plamiga aylanadi va yakuniy baholash uchun yangi ko'rilmagan to'plam kerak bo'ladi.

## Gemini, nutq va Live (2026-11-25 holati)

- **Google Search grounding** bepul tarifda ishlamadi (`429 RESOURCE_EXHAUSTED`) — kod va simulyatsiya testlari bor,
  lekin haqiqiy grounded javob (manbalar, Search Suggestions) shu kalit bilan olinmadi. Billing yoqilgach
  `python scripts/gemini_smoke.py` qayta ishga tushirilishi kerak. Hozircha DuckDuckGo/Wikipedia zaxirasi ishlaydi.
- `gemini-3.8-flash` sinov kuni `504 DEADLINE_EXCEEDED` qaytardi; ishlar `gemini-3.5-flash-lite` orqali bajarildi.
  Vaqtincha bo'lishi mumkin — model zanjiri buni avtomatik hal qiladi, lekin birinchi so'rov ~20 s kechikadi.
- STT taqqoslash **sintetik TTS nutqida** o'tkazilgan; real odam nutqi, shovqinli muhit va turli talaffuz uchun WER
  hali o'lchanmagan. Gemini Transcribe so'z darajasidagi ishonch qiymatini bermaydi (`asr_confidence = None`).
- Gemini Live **real mikrofon bilan** hali sinalmagan (sinov sintetik nutq oqimi bilan). macOS'da aks-sado
  so'ndirish yo'q — quloqchinsiz barge-in o'z ovozidan ham ishga tushishi mumkin. Gap o'rtasidagi uzun pauza
  (rus tilidagi sinovda) server VAD tomonidan navbat tugashi deb olindi.
- Live suhbat davomida desktop buyrug'i tasdiq talab qilsa, tasdiq dialogi interfeysda chiqadi; Live modeli natijani
  tasdiq yakunlangach oladi.
- Whisper bu Mac'da `faster-whisper` (CPU) da ishladi — MLX (Apple GPU) faol emas, shuning uchun sekin (~10 s).
- Fayl qidiruvi sana/tur bo'yicha filtrlamaydi ("kecha yuklab olgan PDF" — nom bo'yicha qidiriladi).

## Oqimli ovoz (2026-11-25)

- Odam nutqi bilan (sintetik ovoz emas) kechikish va aniqlik hali o'lchanmagan; real mikrofon sinovi karnaydan
  ijro etilgan sintetik ovoz bilan (3 namuna).
- Ko'p holatda (7/10) server yakuniy matni 1.2 s ichida kelmaydi va oxirgi oraliq matn olinadi — sinovda ular
  to'g'ri edi, lekin oraliq matn ba'zan to'liq bo'lmasligi mumkin (`finalized_by=interim` metadata'da).
- TTS (edge-tts) birinchi ovozi ~1.2–1.8 s — eng katta qolgan kechikish; qisqa takroriy javoblar keshlanadi.
  Gemini Live suhbat rejimida bu yo'q (native audio).
- Oqimli rejimda "Xadicha" kabi wake-word doimiy tinglash yo'q — mikrofon tugmasi yoki Space bilan boshlanadi.
