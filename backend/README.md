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
├── providers/        # Claude, Ollama, qoida asosidagi (A rejimi) — provayderdan mustaqil
├── adapters/         # macOS (open, AppleScript), Windows (start, UIA), dry-run
├── vision/screen.py  # ekran surati (Retina koordinatalari bilan)
├── speech/           # faster-whisper STT, ayol ovozi TTS
├── storage.py        # SQLite: tarix, statistika, sozlamalar
├── service.py        # agent + nutq + tasdiqlar + hodisalar
├── api.py            # FastAPI + WebSocket
└── __main__.py       # terminal interfeysi
```

## Holati (halollik bilan)

| Qism | Holat |
|---|---|
| Agent sikli (A/B/C), xavfsizlik, tasdiq, to'xtatish | ✅ avtomatik testlardan o'tgan (simulyatsiya qilingan model va adapter bilan) |
| FastAPI + WebSocket | ✅ testlardan o'tgan |
| macOS adapteri | ⚠️ yozilgan, real Mac'da hali sinalmagan |
| Windows adapteri | ⚠️ yozilgan, Windows qurilmasida sinalmagan |
| Claude / Ollama provayderlari | ⚠️ yozilgan, real model bilan hali sinalmagan |
| STT (faster-whisper), TTS | ⚠️ yozilgan; o'zbekcha aniqlik va talaffuz sinalmagan |
| OCR, Accessibility daraxti | ⏳ rejada |
