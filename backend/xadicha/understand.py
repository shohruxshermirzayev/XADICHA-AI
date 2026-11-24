"""Buyruqni tushunish va ishonchni baholash (nutq tanish ishonchidan ALOHIDA).

Asosiy qoida: foydalanuvchi so'zlari hech qachon jimgina almashtirilmaydi. Agar niyat yoki ilova nomi
aniq bo'lmasa, `needs_clarification=True` va (bo'lsa) `suggestion` — taklif qilingan aniq buyruq qaytariladi.
Interfeys asl matnni ko'rsatib, foydalanuvchidan tasdiq so'raydi.

Ikki xil ishonch:
  - asr_confidence  — Whisper matnni qanchalik ishonch bilan eshitdi (speech/stt.py);
  - intent_confidence — matndan niyat va obyekt (ilova nomi va h.k.) qanchalik aniq chiqdi (shu modul).

Bu qoida asosidagi tahlil; aniqligi o'lchanmagan (benchmark: backend/benchmark/).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field

from .providers.rule_based import APP_ALIASES, is_simple, parse_command

ASR_LOW = 0.55          # bundan past — eshitilgan matnni ko'rsatib tasdiq so'raladi
FUZZY_SUGGEST = 0.6     # ilova nomi o'xshashligi shundan yuqori bo'lsa — taklif qilinadi
FUZZY_EXACT = 0.97

# Tez-tez ishlatiladigan ilovalar (macOS + Windows). Ro'yxatda yo'q ilova ham ochilishi mumkin —
# u holda shunchaki "noma'lum ilova" deb past ishonch beriladi, taqiqlanmaydi.
KNOWN_APPS = [
    "Safari", "Google Chrome", "Firefox", "Microsoft Edge", "Telegram", "WhatsApp", "Notes", "Calculator",
    "Calendar", "Mail", "Messages", "Music", "Photos", "Finder", "System Settings", "Terminal", "TextEdit",
    "Preview", "Maps", "FaceTime", "App Store", "Spotify", "Microsoft Word", "Microsoft Excel",
    "Microsoft PowerPoint", "Visual Studio Code", "Zoom", "Reminders", "Contacts", "Clock", "Weather",
    "Pages", "Numbers", "Keynote", "Xcode", "Notepad", "File Explorer", "Paint", "Slack", "Discord",
]

_ALIASES = APP_ALIASES

_CYR2LAT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
})

_OPEN_WORDS = r"(?:och(?:ib\s*ber|gin|ing)?|ishga\s*tushir|open|launch|start|открой(?:те)?|запусти|оч(?:иб\s*бер)?)"

_SUGGEST = {
    "open_app": {"uz": "{x} ni och", "ru": "Открой {x}", "en": "Open {x}"},
}


@dataclass
class Analysis:
    original: str
    normalized: str
    intent: str
    intent_confidence: float
    needs_clarification: bool
    reason: str   # ok | low_asr_confidence | unknown_app | unknown_intent | normalized_particle
    suggestion: str | None = None
    candidates: list[str] = field(default_factory=list)
    app: str | None = None

    def public(self) -> dict:
        d = asdict(self)
        d["intent_confidence"] = round(self.intent_confidence, 2)
        return d


def normalize(text: str) -> tuple[str, list[str]]:
    """Belgilarni bir xillashtiradi va tez-tez uchraydigan ASR xatolarini qayd qiladi.
    Qaytaradi: (normallashtirilgan matn, qo'llangan tuzatishlar ro'yxati)."""
    notes: list[str] = []
    t = text.strip()
    t = re.sub(r"[ʻʼ’‘`´]", "'", t)
    t = re.sub(r"\s+", " ", t).strip(" .!?,")
    # Whisper "ni" qo'shimchasini ko'pincha "in" yoki ajratib "n i" deb yozadi: "Staffar in och"
    t2 = re.sub(r"(\S)\s+in\s+(" + _OPEN_WORDS + r")\b", r"\1 ni \2", t, flags=re.I)
    if t2 != t:
        notes.append("particle_in_to_ni")
        t = t2
    return t, notes


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9' ]", "", name.lower().translate(_CYR2LAT)).strip()


def match_app(name: str) -> tuple[str | None, float, list[str]]:
    """(eng yaqin ma'lum ilova, o'xshashlik 0..1, nomzodlar)."""
    raw = name.strip()
    k = _key(raw)
    if not k:
        return None, 0.0, []
    if raw.lower() in _ALIASES:
        return _ALIASES[raw.lower()], 1.0, [_ALIASES[raw.lower()]]
    if k in _ALIASES:
        return _ALIASES[k], 1.0, [_ALIASES[k]]
    pool = {_key(a): a for a in KNOWN_APPS}
    pool.update({_key(a): v for a, v in _ALIASES.items()})
    scored: dict[str, float] = {}
    for pk, app in pool.items():
        r = difflib.SequenceMatcher(None, k, pk).ratio()
        if r > scored.get(app, 0):
            scored[app] = r
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])
    best, score = ranked[0]
    candidates = [a for a, s in ranked[:3] if s >= FUZZY_SUGGEST]
    return best, score, candidates


def _extract_app(text: str) -> str:
    """"X ni och", "X och", "открой X", "open X" — ilova qismini ajratadi (qoida asosidagi tahlil topmasa)."""
    m = re.search(_OPEN_WORDS + r"\s+(.+)$", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"^(.+?)\s*(?:'?ni|ни)?\s+" + _OPEN_WORDS + r"$", text, re.I)
    return m.group(1) if m else ""


def understand(text: str, language: str = "uz", asr_confidence: float | None = None,
               llm_available: bool = True) -> Analysis:
    """llm_available — murakkab buyruqni model bajara oladimi (qoida asosidagi rejimda — yo'q)."""
    original = text
    norm, notes = normalize(text)
    if not is_simple(norm) or (llm_available and parse_command(norm, language)[0] == "unknown"
                               and not _extract_app(norm)):
        # Ko'p qadamli yoki qoida tushunmaydigan buyruq — modelga topshiriladi (aniqlashtirish faqat ASR past bo'lsa)
        a = Analysis(original=original, normalized=norm, intent="delegated_to_model", intent_confidence=0.5,
                     needs_clarification=not llm_available, reason="ok" if llm_available else "unknown_intent")
        if asr_confidence is not None and asr_confidence < ASR_LOW:
            a.needs_clarification, a.reason = True, "low_asr_confidence"
        return a
    intent, actions, _reply = parse_command(norm, language)
    app_raw = actions[0].app if intent == "open_app" and actions else None
    if intent == "unknown":
        cand = _extract_app(norm)
        if cand:
            intent, app_raw = "open_app", cand

    a = Analysis(original=original, normalized=norm, intent=intent, intent_confidence=0.9,
                 needs_clarification=False, reason="ok")

    if intent == "unknown":
        a.intent_confidence, a.needs_clarification, a.reason = 0.2, True, "unknown_intent"
    elif intent == "open_app" and app_raw:
        app_raw = re.sub(r"['’]?(?:ni|ни)$", "", app_raw.strip(), flags=re.I).strip(" '\"")
        best, score, candidates = match_app(app_raw)
        a.candidates = candidates
        if best and score >= FUZZY_EXACT:
            a.app, a.intent_confidence = best, 0.95
        elif best and score >= FUZZY_SUGGEST:
            # O'xshash ilova bor, lekin aynan emas — taklif qilamiz, o'zimiz almashtirmaymiz
            a.app = best
            a.intent_confidence = round(0.4 + 0.4 * score, 2)
            a.needs_clarification, a.reason = True, "unknown_app"
        else:
            # Ro'yxatda yo'q ilova — taqiqlanmaydi, lekin ishonch past
            a.app, a.intent_confidence = app_raw[:1].upper() + app_raw[1:], 0.5
        if a.app:
            a.suggestion = _SUGGEST["open_app"].get(language, _SUGGEST["open_app"]["en"]).format(x=a.app)

    if "particle_in_to_ni" in notes and not a.needs_clarification:
        a.intent_confidence = min(a.intent_confidence, 0.7)
        a.needs_clarification, a.reason = True, "normalized_particle"

    if asr_confidence is not None and asr_confidence < ASR_LOW:
        a.needs_clarification = True
        if a.reason == "ok":
            a.reason = "low_asr_confidence"
    return a
