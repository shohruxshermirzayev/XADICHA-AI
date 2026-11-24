"""Qoida asosidagi provayder — modelsiz.

Ikki vazifasi bor:
1) Eksperimentdagi A yondashuv (faqat ovozli buyruq, ekransiz, tekshiruvsiz) uchun bazaviy usul.
2) Model mavjud bo'lmaganda oddiy buyruqlarni bajaruvchi zaxira.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import Action, Decision, Plan, RiskLevel
from ..vision.screen import Screenshot
from .base import LLMProvider

# Lotin va kirill o'zbek yozuvi, rus va ingliz tillari
_OPEN = (r"(?:open|launch|start|och(?:ib\s*ber)?|ishga\s*tushir|откро(?:й|йте)|открыть|запусти"
         r"|(?<![а-яёўқғҳ])оч(?:иб\s*бер)?(?![а-яёўқғҳ])|ишга\s*тушир)")
_FOLDER = r"(?:folder|papka|папк[уа])"

_REPLY = {
    "open": {"uz": "{x} ochildi.", "ru": "{x} открыт.", "en": "{x} is open."},
    "url": {"uz": "Sahifa ochildi.", "ru": "Страница открыта.", "en": "The page is open."},
    "folder": {"uz": "Papka yaratildi.", "ru": "Папка создана.", "en": "The folder was created."},
    "unknown": {"uz": "Kechirasiz, bu buyruqni tushunmadim.", "ru": "Извините, я не поняла команду.",
                "en": "Sorry, I did not understand the command."},
}

_URL_RE = re.compile(r"(https?://\S+|\b[\w-]+\.(?:com|uz|ru|org|net|dev|io)\b\S*)", re.I)
_SEARCH_RE = re.compile(
    r"(?:google|search|qidir|izla|найди|поищи)\s*(?:da|for|в\s*google)?\s*[:\-]?\s*(.+)$", re.I)


# Kirillda aytilgan/yozilgan ilova nomlari — tizimdagi haqiqiy nomga (macOS `open -a` lotin nomni kutadi)
_CYR_APPS = {
    "сафари": "Safari", "телеграм": "Telegram", "телеграмм": "Telegram", "хром": "Google Chrome",
    "гугл хром": "Google Chrome", "заметки": "Notes", "нотс": "Notes", "калькулятор": "Calculator",
    "файндер": "Finder", "музыка": "Music", "почта": "Mail", "календарь": "Calendar",
    "ютуб": "YouTube", "ворд": "Microsoft Word", "эксель": "Microsoft Excel",
}


# Mahalliy nomlar (aniq moslik, taxmin emas) va qisqartmalar → haqiqiy ilova nomi
APP_ALIASES = {
    "chrome": "Google Chrome", "xrom": "Google Chrome", "gugl xrom": "Google Chrome", "edge": "Microsoft Edge",
    "kalkulyator": "Calculator", "kalkulator": "Calculator", "eslatmalar": "Notes", "qaydlar": "Notes",
    "kalendar": "Calendar", "taqvim": "Calendar", "pochta": "Mail", "musiqa": "Music", "rasmlar": "Photos",
    "sozlamalar": "System Settings", "settings": "System Settings", "terminal": "Terminal", "word": "Microsoft Word",
    "vord": "Microsoft Word", "excel": "Microsoft Excel", "eksel": "Microsoft Excel", "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code", "telegramm": "Telegram", "bloknot": "Notepad", "provodnik": "File Explorer",
    "whatsap": "WhatsApp", "vatsap": "WhatsApp",
    **_CYR_APPS,
}


def _reply(kind: str, lang: str, **kw: str) -> str:
    return _REPLY[kind].get(lang, _REPLY[kind]["en"]).format(**kw)


# ---------------- Tizim boshqaruvi: ovoz va yorqinlik ----------------
_VOL = r"(?:ovoz\w*|tovush\w*|овоз\w*|товуш\w*|звук\w*|громкост\w*|volume|sound)"
_BRI = r"(?:yorug'lik\w*|yorqinlik\w*|ravshanlik\w*|ёруғлик\w*|ёрқинлик\w*|равшанлик\w*|яркост\w*|brightness)"
_UP = (r"(?:ko'tar\w*|oshir\w*|balan\w*|kuchaytir\w*|ko'paytir\w*|кўтар\w*|ошир\w*|баланд\w*|кучайтир\w*"
       r"|увелич\w*|прибав\w*|подним\w*|up|increase|raise|higher)")
_DOWN = (r"(?:pasaytir\w*|kamaytir\w*|past\w*|sekin\w*|tushir\w*|пасайтир\w*|камайтир\w*|паст\w*|тушир\w*"
         r"|уменьш\w*|убав\w*|сниз\w*|down|decrease|lower|reduce)")
_OFF = r"(?:o'chir\w*|ўчир\w*|выключ\w*|отключ\w*|off)"
_ON = r"(?:yoq\b|yoqib\w*|yoqing|ёқ\b|ёқиб\w*|ёқинг|включ\w*|on)"

_SYS_REPLY = {
    "volume_up": {"uz": "Ovoz balandlatildi.", "ru": "Громкость увеличена.", "en": "Volume turned up."},
    "volume_down": {"uz": "Ovoz pasaytirildi.", "ru": "Громкость уменьшена.", "en": "Volume turned down."},
    "volume_set": {"uz": "Ovoz {n}% ga o'rnatildi.", "ru": "Громкость установлена на {n}%.", "en": "Volume set to {n}%."},
    "mute": {"uz": "Ovoz o'chirildi.", "ru": "Звук выключен.", "en": "Sound muted."},
    "unmute": {"uz": "Ovoz yoqildi.", "ru": "Звук включён.", "en": "Sound unmuted."},
    "brightness_up": {"uz": "Ekran yorqinligi oshirildi.", "ru": "Яркость увеличена.", "en": "Brightness turned up."},
    "brightness_down": {"uz": "Ekran yorqinligi pasaytirildi.", "ru": "Яркость уменьшена.", "en": "Brightness turned down."},
}


def _one_system(part: str) -> Action | None:
    t = re.sub(r"[ʻʼ’‘`´]", "'", part.lower()).strip(" .!?")
    num = re.search(r"(\d{1,3})\s*(?:%|foiz|фоиз|процент\w*|percent)?", t)
    n = int(num.group(1)) if num and int(num.group(1)) <= 100 else None
    vol, bri = re.search(_VOL, t), re.search(_BRI, t)
    # Bir so'zli iboralar
    if re.fullmatch(r"(?:сделай\s+)?громче|louder|turn (?:it )?up", t):
        return Action(type="system", control="volume_up")
    if re.fullmatch(r"(?:сделай\s+)?тише|quieter|turn (?:it )?down", t):
        return Action(type="system", control="volume_down")
    if re.fullmatch(r"mute|без звука|ovozsiz(?: qil\w*)?|овозсиз(?: қил\w*)?", t):
        return Action(type="system", control="mute")
    if re.fullmatch(r"unmute", t):
        return Action(type="system", control="unmute")
    if re.fullmatch(r"(?:сделай\s+)?(?:экран\s+)?ярче|brighter|(?:ekran\w*\s+)?yorqinroq(?: qil\w*)?|(?:экран\w*\s+)?ёрқинроқ(?: қил\w*)?", t):
        return Action(type="system", control="brightness_up")
    if re.fullmatch(r"(?:сделай\s+)?(?:экран\s+)?темнее|dimmer|darker|(?:ekran\w*\s+)?xiraroq(?: qil\w*)?|(?:экран\w*\s+)?хирароқ(?: қил\w*)?", t):
        return Action(type="system", control="brightness_down")
    if bri or re.search(r"ekran\w*\s+(?:yorug'|yorq)|экран\w*\s+(?:ёруғ|ёрқ)", t):
        if re.search(_UP, t):
            return Action(type="system", control="brightness_up", amount=n)
        if re.search(_DOWN, t):
            return Action(type="system", control="brightness_down", amount=n)
        return None
    if vol:
        if n is not None and not re.search(_UP + "|" + _DOWN, t):
            return Action(type="system", control="volume_set", amount=n)
        if re.search(_OFF, t):
            return Action(type="system", control="mute")
        if re.search(_ON, t):
            return Action(type="system", control="unmute")
        if re.search(_UP, t):
            return Action(type="system", control="volume_up", amount=n)
        if re.search(_DOWN, t):
            return Action(type="system", control="volume_down", amount=n)
    return None


def parse_system(text: str) -> list[Action] | None:
    """"ovozni ko'tar", "сделай тише", "brightness up", "ovozni ko'tar va yorug'likni oshir" — har bir qism
    tizim buyrug'i bo'lsagina natija qaytaradi (aks holda None — boshqa tahlilga o'tadi)."""
    parts = [p for p in re.split(r"\s+(?:va|hamda|and|и|ва)\s+|[,;]", text.strip()) if p.strip()]
    if not parts:
        return None
    actions = [_one_system(p) for p in parts]
    return actions if all(actions) else None  # type: ignore[return-value]


def system_reply(actions: list[Action], lang: str) -> str:
    out = []
    for a in actions:
        r = _SYS_REPLY[a.control or ""]
        out.append(r.get(lang, r["en"]).format(n=a.amount))
    return " ".join(out)


_MULTI = re.compile(r"(\s(va|and|и|keyin|then|потом|затем)\s|[,;]|\bdeb\b|\byoz\b|\btype\b|\bнапиши\b)", re.I)
FAST_INTENTS = {"open_app", "open_url", "web_search", "create_folder", "system"}


def is_simple(text: str) -> bool:
    """Bitta harakatli oddiy buyruqmi (bog'lovchilarsiz, matn yozishsiz)."""
    return not _MULTI.search(text.strip())


def parse_command(text: str, language: str = "en") -> tuple[str, list[Action], str]:
    """(niyat, harakatlar, javob) qaytaradi."""
    t = text.strip().rstrip(".!?")
    low = t.lower()

    sys_actions = parse_system(t)
    if sys_actions:
        return "system", sys_actions, system_reply(sys_actions, language)

    m = _URL_RE.search(t)
    if m and re.search(_OPEN + r"|sayt|site|сайт|zayti", low):
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        return "open_url", [Action(type="open_url", url=url)], _reply("url", language)

    m = _SEARCH_RE.search(t)
    if m and m.group(1).strip():
        from urllib.parse import quote_plus

        q = m.group(1).strip()
        return "web_search", [Action(type="open_url", url=f"https://www.google.com/search?q={quote_plus(q)}")], \
            _reply("url", language)

    if re.search(_FOLDER, low) and re.search(r"(?:create|make|yarat|och|созда|ярат)", low):
        name_m = re.search(r"[\"«“']([^\"»”']+)[\"»”']", t)
        name = name_m.group(1) if name_m else "Yangi papka"
        return "create_folder", [Action(type="create_folder", path=f"~/Desktop/{name}")], \
            _reply("folder", language)

    # "Safari ni och", "Safari'ni och", "открой Safari", "open Safari"
    m = re.search(_OPEN + r"\s+(.+)$", t, re.I)
    if m:
        app = m.group(1)
    else:
        m = re.search(r"^(.+?)(?:\s*['’‘]?\s*(?:ni|ni\s+ham|-ni|ни|ни\s+ҳам|-ни))\s+" + _OPEN, t, re.I)
        app = m.group(1) if m else ""
    app = re.sub(r"^(the|app|application|ilova(?:si)?|приложение)\s+", "", app.strip(), flags=re.I)
    app = re.sub(r"\s+(app|ilovasi(?:ni)?|приложение)$", "", app, flags=re.I).strip(" '\"’")
    if app:
        app = APP_ALIASES.get(app.lower(), app)   # faqat aniq moslik; o'xshashlik bo'yicha taxmin — understand.py
        app = app[0].upper() + app[1:]
        return "open_app", [Action(type="open_app", app=app)], _reply("open", language, x=app)

    return "unknown", [], _reply("unknown", language)


class RuleBasedProvider(LLMProvider):
    name = "rules"
    supports_vision = False

    def complete(self, system: str, user: str, screen: Screenshot | None) -> str:  # pragma: no cover
        raise NotImplementedError

    def decide(self, instruction: str, history: list[dict[str, Any]], screen: Screenshot | None,
               language: str) -> Decision:
        intent, actions, reply = parse_command(instruction, language)
        if history or not actions:
            return Decision(intent=intent, done=True, final_message=reply,
                            previous_step_ok=(history[-1]["status"] != "failed") if history else None)
        return Decision(intent=intent, action=actions[0], risk=RiskLevel.low, final_message=reply)

    def plan(self, instruction: str, language: str) -> Plan:
        intent, actions, reply = parse_command(instruction, language)
        return Plan(intent=intent, steps=[Decision(intent=intent, action=a) for a in actions], final_message=reply)
