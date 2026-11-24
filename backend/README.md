# XADICHA AI — backend (agent yadrosi)

Python **3.10+** (tavsiya: 3.12), FastAPI. macOS bilan keladigan Python 3.9 **ishlamaydi**. Nutq → ekran konteksti → reja → xavf baholash → bajarish → tekshiruv → tiklanish → ovozli javob.

## O'rnatish (macOS)

```bash
cd ~/MAGISTRATURA/"XADICHA AI"/backend
brew install python@3.12          # yoki python.org dan 3.12 o'rnatuvchisi
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env        # keyin .env ni tahrirlang
```

## Ishga tushirish

```bash
python -m xadicha --dry-run          # xavfsiz sinov: hech narsa bajarilmaydi
python -m xadicha                    # matnli buyruqlar (C rejimi)
python -m xadicha --voice            # ovozli buyruqlar
python -m xadicha --mode A           # eksperiment rejimlari: A | B | C
python -m xadicha serve              # API: http://127.0.0.1:8765  (interfeys uchun)
python -m pytest -q                  # testlar
```

## macOS ruxsatlari

**System Settings → Privacy & Security** bo'limida Terminal'ga (yoki ishlatayotgan ilovangizga) quyidagi ruxsatlarni bering:
- **Accessibility** — sichqoncha va klaviaturani boshqarish
- **Screen Recording** — ekranni ko'rish
- **Microphone** — ovozli buyruqlar

## Tuzilishi

```
xadicha/
├── agent.py          # A/B/C rejimlari, tekshiruv va tiklanish sikli
├── models.py         # Pydantic: Action, Decision, TaskRecord, RiskLevel
├── safety.py         # xavf tasnifi, tasdiq siyosati, taqiqlangan harakatlar
├── understand.py     # buyruqni tushunish, niyat ishonchi, aniqlashtirish
├── metrics.py        # WER, CER, TSR va boshqa metrikalar
├── benchmark.py      # A/B/C benchmark runner (xom JSONL loglar)
├── providers/        # Claude, Ollama, qoida asosidagi (A rejimi) — provayderdan mustaqil
├── adapters/         # macOS (open, AppleScript), Windows (start, UIA), dry-run
├── vision/screen.py  # ekran surati, rasm → ekran koordinatasi (Retina)
├── vision/context.py # OCR (Apple Vision) va accessibility daraxti (AXUIElement) — ixtiyoriy
├── speech/           # faster-whisper STT, ayol ovozi TTS
├── storage.py        # SQLite: tarix, statistika, sozlamalar
├── service.py        # agent + nutq + tasdiqlar + hodisalar
├── api.py            # FastAPI + WebSocket
└── __main__.py       # terminal interfeysi
```

## Holati (halollik bilan)

| Qism | Holat |
|---|---|
| Agent sikli (A/B/C), xavfsizlik, tasdiq, to'xtatish | ✅ avtomatik testlar (simulyatsiya: soxta model, dry-run adapter) |
| FastAPI + WebSocket (yagona holat, Host/Origin/token himoyasi) | ✅ testlardan o'tgan |
| Nutq ishonchi va aniqlashtirish (`understand.py`) | ✅ testlar; aniqlik o'lchanmagan |
| OCR / accessibility provayder interfeysi | ✅ soxta API bilan testlangan; real Mac'da sinalmagan |
| macOS adapteri | ⚠️ real Mac'da avtomatik sinalmagan |
| Windows adapteri | ⚠️ Windows qurilmasida sinalmagan |
| Claude / Ollama provayderlari | ⚠️ real model bilan avtomatik sinalmagan |
| STT (faster-whisper / MLX), TTS | ⚠️ o'zbekcha aniqlik va talaffuz o'lchanmagan |

## Qo'shimcha vositalar

```bash
pip install -r requirements-macos-optional.txt   # OCR (Apple Vision) + accessibility (AXUIElement), ixtiyoriy
python scripts/mac_selftest.py                   # real Mac tekshiruvi (har qadam ruxsat bilan)
python -m xadicha.benchmark --dry-run            # benchmark harness tekshiruvi (SIMULYATSIYA)
python -m xadicha.benchmark --modes A,B,C        # real benchmark (macOS + model)
```

## Xavfsizlik siyosati (qisqacha)

- Model xavfni faqat **oshira oladi**, pasaytira olmaydi.
- Tasdiq funksiyasi aniq `True` qaytarmasa — harakat **bajarilmaydi** (rad, muddat tugashi, to'xtatish).
- Tasdiq bilan ham bajarilmaydi: tizim papkalari (`/System`, `/etc`, `/private`, `C:\Windows`, `C:\Program Files (x86)` …),
  `~/.ssh`, `~/Library`, `~/.config` kabi sezgir joylar, uy papkasi va `~/Documents` kabi asosiy papkalarning o'zini o'chirish,
  `http/https` bo'lmagan manzillar (`file:`, ilova yo'li), maxsus qobiq belgilari bor ilova nomlari.
- Yo'llar `..` va symlinklar yechilgandan keyin tekshiriladi; nisbiy yo'l workspace'ga nisbatan olinadi.

Batafsil: [../docs/TECHNICAL.md](../docs/TECHNICAL.md).
