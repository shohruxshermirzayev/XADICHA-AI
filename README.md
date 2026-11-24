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
