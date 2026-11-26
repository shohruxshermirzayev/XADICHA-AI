"""Qoida asosidagi provayder — modelsiz.

Ikki vazifasi bor:
1) Eksperimentdagi A yondashuv (faqat ovozli buyruq, ekransiz, tekshiruvsiz) uchun bazaviy usul.
2) Model mavjud bo'lmaganda oddiy buyruqlarni bajaruvchi zaxira.
"""

from __future__ import annotations

import platform
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
    "ютуб": "YouTube", "ворд": "Microsoft Word", "эксель": "Microsoft Excel", "терминал": "Terminal",
    "настройки": "System Settings", "финдер": "Finder", "сафарини": "Safari", "превью": "Preview",
}


# Tez-tez ishlatiladigan ilovalar (macOS + Windows)
KNOWN_APPS = [
    "Safari", "Google Chrome", "Firefox", "Microsoft Edge", "Telegram", "WhatsApp", "Notes", "Calculator",
    "Calendar", "Mail", "Messages", "Music", "Photos", "Finder", "System Settings", "Terminal", "TextEdit",
    "Preview", "Maps", "FaceTime", "App Store", "Spotify", "Microsoft Word", "Microsoft Excel",
    "Microsoft PowerPoint", "Visual Studio Code", "Zoom", "Reminders", "Contacts", "Clock", "Weather",
    "Pages", "Numbers", "Keynote", "Xcode", "Notepad", "File Explorer", "Paint", "Slack", "Discord",
]

_KNOWN_LOWER = {a.lower() for a in KNOWN_APPS}
_DEFAULT_BROWSER = "Microsoft Edge" if platform.system() == "Windows" else "Safari"

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
    # "brauzer" — tizimning standart brauzeri (macOS'da Safari har doim bor)
    "brauzer": _DEFAULT_BROWSER, "brauzerni": _DEFAULT_BROWSER, "браузер": _DEFAULT_BROWSER, "браузерни": _DEFAULT_BROWSER,
    "browser": _DEFAULT_BROWSER, "the browser": _DEFAULT_BROWSER, "web browser": _DEFAULT_BROWSER,
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

# Batareya so'rovi: "zaryad qancha", "batareya necha foiz", "сколько заряда", "battery level"…
# "quvvat" — faqat so'roq bilan ("kompyuter quvvatini o'chir" — batareya so'rovi emas)
BATTERY = re.compile(
    r"\b(?:batare\w*|akkumulyator\w*|zaryad\w*|батаре\w*|аккумулятор\w*|заряд\w*|battery|batteries)|"
    r"\b(?:quvvat\w*|қувват\w*)\s+(?:qancha|necha|nechchi|nech|foiz|qoldi|қанча|неча|фоиз|қолди)|"
    r"\b(?:qancha|necha|қанча|неча)\s+(?:quvvat|қувват)\w*|how much (?:charge|power) (?:is )?left|charge level",
    re.I)

_SYS_REPLY = {
    "volume_up": {"uz": "Ovoz balandlatildi.", "ru": "Громкость увеличена.", "en": "Volume turned up."},
    "volume_down": {"uz": "Ovoz pasaytirildi.", "ru": "Громкость уменьшена.", "en": "Volume turned down."},
    "battery": {"uz": "Batareya holati tekshirildi.", "ru": "Состояние батареи проверено.", "en": "Battery checked."},
    "screenshot": {"uz": "Skrinshot olindi va Desktop'ga saqlandi.", "ru": "Скриншот сохранён на рабочий стол.",
                   "en": "Screenshot saved to the Desktop."},
    "volume_set": {"uz": "Ovoz {n}% ga o'rnatildi.", "ru": "Громкость установлена на {n}%.", "en": "Volume set to {n}%."},
    "mute": {"uz": "Ovoz o'chirildi.", "ru": "Звук выключен.", "en": "Sound muted."},
    "unmute": {"uz": "Ovoz yoqildi.", "ru": "Звук включён.", "en": "Sound unmuted."},
    "brightness_up": {"uz": "Ekran yorqinligi oshirildi.", "ru": "Яркость увеличена.", "en": "Brightness turned up."},
    "brightness_down": {"uz": "Ekran yorqinligi pasaytirildi.", "ru": "Яркость уменьшена.", "en": "Brightness turned down."},
}


_SCREENSHOT = re.compile(r"\b(?:screenshot|screen shot|skrinshot\w*|скриншот\w*|снимок экрана|"
                         r"(?:ekran|экран)\w*\s+(?:rasm|surat|расм|сурат)\w*(?:\s+(?:ol|qil|ол|қил|сделай)\w*)?)")


def _one_system(part: str) -> Action | None:
    t = re.sub(r"[ʻʼ’‘`´]", "'", part.lower()).strip(" .!?")
    if _SCREENSHOT.search(t):
        return Action(type="system", control="screenshot")
    if BATTERY.search(t) and not re.search(_VOL, t) and not re.search(_BRI, t):
        return Action(type="system", control="battery")   # faqat o'qish — zaryad foizi va holati
    # "ovoz balandligi" — ot (daraja), yo'nalish emas: "ovoz balandligini kamaytir" pastga
    t = re.sub(r"\b(?:balandlig|баландлиг)\w*", "", t)
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
        # Faqat bir ma'noli "gacha": "50 gacha tushir", "уменьши до 30", "turn it down to 20" — aniq qiymatga o'rnatish.
        # "50 foizga tushir" — o'zbek tilida "50 ga kamaytir" ham bo'lishi mumkin, shuning uchun qadam sifatida qoladi.
        target = n is not None and re.search(rf"\b{n}\s*(?:%|foiz|фоиз)?\s*-?(?:gacha|гача)\b|\bдо\s+{n}\b|\bto\s+{n}\b", t)
        if n is not None and (target or not re.search(_UP + "|" + _DOWN, t)):
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


def _uz_duration(m: int) -> str:
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h} soat {mm} daqiqaga"
    return f"{h} soatga" if h else f"{mm} daqiqaga"


def battery_reply(info: dict | None, lang: str) -> str:
    """Batareya javobi foydalanuvchi tilida: "Zaryad 76%, quvvatlanmoqda." Faqat o'qilgan qiymatlardan — to'qilmaydi."""
    lang = lang if lang in ("uz", "ru", "en") else "en"
    if not info or info.get("simulated"):
        return {"uz": "Batareya holati simulyatsiya rejimida o'qilmaydi.",
                "ru": "В режиме симуляции состояние батареи не читается.",
                "en": "Battery status is not read in simulation mode."}[lang]
    if not info.get("present"):
        return {"uz": "Batareya topilmadi.", "ru": "Батарея не найдена.", "en": "No battery found."}[lang]
    p, state, m = int(info["percent"]), info.get("state", ""), info.get("minutes_left")
    if state == "charged" or (p >= 100 and state in ("charging", "ac")):
        tail = {"uz": "to'liq", "ru": "полностью заряжена", "en": "fully charged"}[lang]
    elif state == "charging":
        tail = {"uz": "quvvatlanmoqda", "ru": "идёт зарядка", "en": "charging"}[lang]
    elif state == "ac":
        tail = {"uz": "quvvat manbaiga ulangan", "ru": "подключено к питанию", "en": "plugged in"}[lang]
    elif m:
        h, mm = divmod(m, 60)
        tail = {"uz": f"taxminan {_uz_duration(m)} yetadi",
                "ru": "хватит примерно на " + (f"{h} ч {mm} мин" if h else f"{mm} мин"),
                "en": "about " + (f"{h} h {mm} min" if h else f"{mm} min") + " left"}[lang]
    else:
        tail = ""
    head = {"uz": f"Zaryad {p}%", "ru": f"Заряд {p}%", "en": f"Battery is at {p}%"}[lang]
    text = f"{head}, {tail}." if tail else f"{head}."
    if p < 20 and state == "discharging":
        text += " " + {"uz": "Zaryadlovchini ulashni maslahat beraman.", "ru": "Советую подключить зарядку.",
                       "en": "I recommend plugging in the charger."}[lang]
    return text


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


_SITE = re.compile(r"(google|гугл|youtube|ютуб)", re.I)
_SEARCH_VERB = re.compile(r"(?:qidir\w*|izla\w*|top\w*|қидир\w*|найди|поищи|search(?: for)?|look up|find)", re.I)


_NAME_PATTERNS = (
    r"[\"«“']([^\"»”']+)[\"»”']",                                     # "Hisobot"
    r"(\S+)\s+(?:nomli|degan|номли|деган)\b",                        # Hisobot nomli papka
    r"\b(?:named|called)\s+(\S+)",                                   # a folder named Reports
    r"(?:под названием|с именем|с названием)\s+(\S+)",               # папку с именем Отчёт
)
_DESKTOP = r"\b(?:desktop|ish stol|рабоч\w* стол|иш стол)"
_DOCUMENTS = r"\b(?:documents|hujjatlar|документ\w*|ҳужжатлар)\b"


def folder_path(text: str) -> str:
    """Papka yo'li: nom (qo'shtirnoq, "X nomli", "named X") + joy (aniq yo'l, Desktop, Documents).
    Joy aytilmasa — NISBIY nom qaytadi: agent uni workspace ichida yaratadi (agent._execute)."""
    name = ""
    for pat in _NAME_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            name = m.group(1).strip(" .,!?")
            break
    name = re.sub(r"[/\\]", "-", name) or "Yangi papka"
    low = text.lower()
    loc = re.search(r"((?:~|/Users|/home|[A-Za-z]:\\)[^\s\"«»]*)", text)   # aniq yo'l: "~/XADICHA_TEST ichida"
    if loc:
        return f"{loc.group(1).rstrip('/')}/{name}"
    if re.search(_DESKTOP, low):
        return f"~/Desktop/{name}"
    if re.search(_DOCUMENTS, low):
        return f"~/Documents/{name}"
    return name


def browser_search(text: str) -> tuple[str, str] | None:
    """"Google dan Python haqida qidir" → ("google", "Python"); "YouTube'da musiqa qidir" → ("youtube", "musiqa")."""
    m = _SITE.search(text)
    if not m or not _SEARCH_VERB.search(text):
        return None
    site = "youtube" if m.group(1).lower() in ("youtube", "ютуб") else "google"
    q = re.sub(r"[ʻ’‘`´]", "'", text)
    q = re.sub(r"\b(?:google|гугл|youtube|ютуб)\w*(?:\s*['’]?\s*(?:da|dan|de|ga|да|дан|га))?\b", " ", q, flags=re.I)
    q = re.sub(r"\b(?:in|on|в|на)\s*$", " ", q.strip(), flags=re.I)
    q = _SEARCH_VERB.sub(" ", q)
    q = re.sub(r"\b(?:haqida|ҳақида|ma'lumot|маълумот|ni|ни|about|for|о|об|про|в|на|in|on|ib ber|ber)\b", " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" .!?:'\"")
    return (site, q) if q else None


def parse_command(text: str, language: str = "en") -> tuple[str, list[Action], str]:
    """(niyat, harakatlar, javob) qaytaradi."""
    t = text.strip().rstrip(".!?")
    low = t.lower()

    sys_actions = parse_system(t)
    if sys_actions:
        return "system", sys_actions, system_reply(sys_actions, language)

    m = _URL_RE.search(t)
    if m and re.search(_OPEN + r"|sayt|site|сайт|zayti|\bkir\b|\bkiring\b|зайди|перейди|go to", low):
        url = m.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        return "open_url", [Action(type="open_url", url=url)], _reply("url", language)

    bq = browser_search(t)
    if bq is not None:
        from urllib.parse import quote_plus

        site, q = bq
        url = (f"https://www.youtube.com/results?search_query={quote_plus(q)}" if site == "youtube"
               else f"https://www.google.com/search?q={quote_plus(q)}")
        return "web_search", [Action(type="open_url", url=url)], _reply("url", language)

    if re.search(_FOLDER, low) and re.search(r"(?:create|make|yarat|och|созда|ярат)", low):
        return "create_folder", [Action(type="create_folder", path=folder_path(t))], _reply("folder", language)

    # Savol buyruq emas: "Which app is open right now?", "Qaysi ilova ochiq?" — modelga qoldiriladi
    if text.strip().endswith("?") or re.match(r"^(?:which|what|is|are|does|qaysi|nima|qanday|какое|какой|что|ли)\b", low):
        return "unknown", [], _reply("unknown", language)

    # "Safari ni och", "Safari'ni och", "открой Safari", "open Safari"
    m = re.search(_OPEN + r"\s+(.+)$", t, re.I)
    if m:
        app = m.group(1)
    else:
        m = re.search(r"^(.+?)(?:\s*['’‘]?\s*(?:ni|ni\s+ham|-ni|ни|ни\s+ҳам|-ни))\s+" + _OPEN, t, re.I)
        app = m.group(1) if m else ""
        if not app:
            # "Safari ochib ber", "Safari ga kir", "Telegram och" — qo'shimchasiz; faqat MA'LUM ilova bo'lsa
            m = re.search(r"^(.+?)\s*(?:['’]?ga\s+kir\w*|\s+" + _OPEN + r")$", t, re.I)
            cand = (m.group(1).strip(" '\"’") if m else "")
            if cand and (cand.lower() in _KNOWN_LOWER or cand.lower() in APP_ALIASES):
                app = cand
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
