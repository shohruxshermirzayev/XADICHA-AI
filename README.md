# XADICHA AI

O'zbek, rus va ingliz tillaridagi tabiiy nutq hamda vizual kontekst asosida kompyuter interfeysini boshqaruvchi multimodal AI agent (magistrlik dissertatsiyasi loyihasi).

```
XADICHA AI/
├── backend/   ← Python agent: nutq, ekran, model, boshqaruv, xavfsizlik, FastAPI
└── src/       ← Next.js interfeys: yordamchi, dashboard, ekran tahlili, tarix, tadqiqot, sozlamalar
```

## Ishga tushirish (ikki Terminal tab)

**1-tab — backend (agent):**
```bash
cd ~/MAGISTRATURA/"XADICHA AI"/backend
source .venv/bin/activate
python -m xadicha serve
```

**2-tab — interfeys:**
```bash
cd ~/MAGISTRATURA/"XADICHA AI"
npm run dev
```

Keyin brauzerda http://localhost:3000 ni oching.

Faqat terminalda ishlatish: `python -m xadicha` (matn) yoki `python -m xadicha --voice --lang uz` (ovoz).
Batafsil: [backend/README.md](backend/README.md).

## Stek

Backend: Python 3.12, FastAPI, Pydantic, SQLite, faster-whisper, Ollama (Qwen 3.5) yoki Claude API.
Interfeys: Next.js 16, Tailwind CSS 4, Motion, lucide-react; shadcn/ui, Magic UI va React Bits registrlari `components.json` da ulangan.

## Tekshirish (testlar)

```bash
cd backend && source .venv/bin/activate && python -m pytest -q   # backend: 106 ta test
cd .. && npm test              # interfeys mantiqi: tarjimalar, WebSocket xabarlari (13 ta test)
npm run lint                   # ESLint
npm run typecheck              # TypeScript
npm run build                  # production build
```

Testlar simulyatsiya qilingan model va **dry-run** adapter bilan ishlaydi — ular real Mac yoki Windows'da
harakat bajarilishini isbotlamaydi. Batafsil: [docs/TECHNICAL.md](docs/TECHNICAL.md).

## Holati (halollik bilan)

| Qism | Holat |
|---|---|
| Agent sikli (A/B/C), xavfsizlik siyosati, tasdiq, favqulodda to'xtatish | ✅ avtomatik testlar (simulyatsiya) |
| Interfeys: tasdiq dialogi, qayta ulanish, 3 tilli interfeys, kirill kiritish | ✅ headless Chrome'da tekshirilgan (dry-run backend bilan) |
| Ekran tahlili | ⚠️ faqat ekran surati + vision model. **OCR va accessibility daraxti yo'q** |
| macOS adapteri | ⚠️ real Mac'da avtomatik sinalmagan |
| Windows adapteri | ⚠️ Windows qurilmasida umuman sinalmagan |
| Mikrofon (sounddevice) va STT/TTS | ⚠️ real mikrofon bilan avtomatik sinalmagan; o'zbekcha aniqlik o'lchanmagan |
| Claude / Ollama provayderlari | ⚠️ real model bilan avtomatik sinalmagan |

Hech bir platforma "production-ready" deb belgilanmagan.

