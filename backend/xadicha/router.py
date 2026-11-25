"""Aqlli marshrutlash: buyruqni eng mos bajarish yo'liga yo'naltiradi.

  fast        — aniq, deterministik buyruq (ovoz/yorqinlik, ma'lum ilova, sayt, papka) → modelsiz, darhol
  tool        — maxsus vosita yetarli (internetdan qidirish, fayl qidirish, havola: "uni yana och")
  autonomous  — murakkab vazifa → LLM: ekran, reja, qadam-baqadam bajarish, tekshiruv, tiklanish
  clarify     — buyruqda zarur obyekt yo'q ("shu faylni top", lekin kontekstda fayl yo'q)
  chat        — oddiy suhbat (salom, rahmat, "sen kimsan", umumiy savol) → faqat javob, HECH QANDAY amal yo'q

Qoida asosidagi; noma'lum yoki murakkab buyruq har doim modelga (autonomous) qoldiriladi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .conversation import Conversation
from .models import Action
from .providers.rule_based import FAST_INTENTS, is_simple, parse_command


@dataclass
class Route:
    path: str                       # fast | tool | autonomous | clarify | chat
    intent: str = ""
    actions: list[Action] = field(default_factory=list)
    reply: str = ""
    resolved_from: str = ""         # havola hal qilingan bo'lsa — asl matn
    note: str = ""
    ref: str = ""                   # havola turi: repeat | last_app | last_url | last_path | result_n


_BROWSER = re.compile(r"google|youtube|ютуб|гугл|brauzer|браузер|browser", re.I)

_SEARCH = [
    re.compile(r"^(?:internet(?:da|dan)\s+)?(?P<q>.+?)\s+haqida\s+(?:ma'lumot\s+)?(?:qidir|top|izla)\w*$", re.I),
    re.compile(r"^internet(?:da|dan)\s+(?P<q>.+?)\s+(?:ni\s+)?(?:qidir|top|izla)\w*$", re.I),
    re.compile(r"^(?:qidir|izla)\w*[:\s]+(?P<q>.+)$", re.I),
    re.compile(r"^(?P<q>.+?)\s*['’]?(?:ni|ни)\s+(?:internetdan\s+)?(?:qidir|izla)\w*$", re.I),
    re.compile(r"^(?P<q>.+?)\s+ҳақида\s+(?:маълумот\s+)?(?:қидир|топ)\w*$", re.I),
    re.compile(r"^(?:найди|поищи)\s+(?:в интернете\s+)?(?:информацию\s+)?(?:о|об|про)\s+(?P<q>.+)$", re.I),
    re.compile(r"^(?:поищи|найди в интернете)\s+(?P<q>.+)$", re.I),
    re.compile(r"^(?:search(?: the web| online| the internet)?(?: for)?|look up|find information (?:about|on))\s+(?P<q>.+)$", re.I),
]
_FILE = [
    re.compile(r"^(?P<q>.+?)\s+(?:nomli\s+)?(?:fayl|hujjat|papka)\w*\s*(?:ni\s+)?(?:top|qidir)\w*(?:\s+ber\w*)?$", re.I),
    re.compile(r"^(?:fayl|hujjat|papka)\w*\s+(?P<q>.+?)\s+(?:ni\s+)?(?:top|qidir)\w*(?:\s+ber\w*)?$", re.I),
    re.compile(r"^(?P<q>.+?)\s+(?:файл|ҳужжат)\w*\s*(?:ни\s+)?(?:топ|қидир)\w*(?:\s+бер\w*)?$", re.I),
    re.compile(r"^найди\s+(?:файл|документ|папку)\s+(?P<q>.+)$", re.I),
    re.compile(r"^find\s+(?:the\s+|a\s+|my\s+)?(?:file|document|folder)\s+(?:named\s+|called\s+)?(?P<q>.+)$", re.I),
]
_PRONOUN = re.compile(r"^(?:shu|o'sha|bu|ana shu|шу|ўша|бу|этот|эту|тот|that|this)$", re.I)

_REVEALED = {"uz": "{x} Finder'da ko'rsatildi.", "ru": "{x} показан в Finder.", "en": "{x} is shown in Finder."}

_NEED_NAME = {"uz": "Qaysi faylni qidiray? Nomini ayting.", "ru": "Какой файл искать? Назовите имя.",
              "en": "Which file should I look for? Please say its name."}


# Amal so'zlari: bular bor gap HECH QACHON suhbat deb olinmaydi (buyruq yo'lida qoladi — xavfsiz tomon)
_ACTION_WORDS = re.compile(
    r"\b(?:och|ishga tushir|yop|qidir|izla|top|yarat|o'chir|ko'rsat|kir|yoz|bos|ovoz|yorug|yorqin|saqla|yubor|"
    r"o'rnat|ko'tar|pasaytir|kamaytir|oshir|ijro|qo'y|aylantir|"
    r"оч|ишга тушир|қидир|топ|ярат|ўчир|кўрсат|кир|ёз|овоз|ёруғ|юбор|кўтар|пасайтир|камайтир|"
    r"откр|запуст|закр|найд|поищ|созда|удал|покаж|громк|ярк|звук|напиш|отправ|установ|сохран|включ|выключ|"
    r"open|launch|start|close|search|find|create|delete|show|type|click|volume|brightness|mute|play|send|"
    r"install|save|turn|set|go to|look up|message|write|tell|say|email|call|remind|"
    r"xabar|qo'ng'iroq|eslat|айт|хабар|сообщ|позвон|напомн|скажи)",
    re.I,
)
# Ekran haqidagi savol — ekranni ko'radigan agentga qoladi
_SCREEN_WORDS = re.compile(r"\b(?:ekran|oyna|экран|окн|screen|window|display)", re.I)
_CHAT_PATTERNS = re.compile(
    r"\b(?:salom|assalom|assalomu|hayrli (?:tong|kun|kech)|xayrli (?:tong|kun|kech)|xayr|ko'rishguncha|"
    r"rahmat\w*|raxmat\w*|tashakkur\w*|qalaysan|qalaysiz|yaxshimisiz|yaxshimisan|ishlar qalay|nima gap|"
    r"kimsan|kimsiz|isming|ismingiz|nima qila olasan|nima qila olasiz|nimalar qila ola|imkoniyatlaring|"
    r"kayfiyat\w*|charchad\w*|zerik\w*|xursand\w*|xafa\w*|"
    r"салом|ассалом|раҳмат|рахмат|ташаккур|қалайсиз|қалайсан|яхшимисиз|кимсан|кимсиз|хайр|"
    r"привет\w*|здравствуй\w*|добр(?:ое|ый|ой) (?:утро|день|вечер)|пока|до свидания|спасибо|благодар\w*|как дела|как ты|"
    r"кто ты|как тебя зовут|что ты умеешь|настроени\w*|устал\w*|скучн\w*|грустн\w*|"
    r"hello|hi|hey|good (?:morning|afternoon|evening|night)|bye|goodbye|thank|thanks|how are you|who are you|"
    r"your name|what can you do|i'?m (?:tired|bored|sad|happy)|i feel)\b",
    re.I,
)
_QUESTION_START = re.compile(
    r"^(?:nima|nega|qanday|qachon|qayer|kim|necha|qaysi|нима|нега|қандай|қачон|қаер|ким|неча|"
    r"что|как|когда|где|кто|почему|зачем|сколько|какой|what|how|when|where|who|why|which|is|are|do|does|can)\b",
    re.I,
)
_SHORT_REACTION = re.compile(r"^(?:ha|xo'p|ok|okay|zo'r|ajoyib|yaxshi|tushunarli|ҳа|хўп|яхши|да|хорошо|отлично|понятно|"
                             r"yes|great|cool|nice|got it)$", re.I)


# "Seni kim yaratgan?" — "yarat"/"создать" amal so'zi bo'lsa ham, bu suhbat (XADICHA'ning yaratuvchisi haqida).
# Shart: XADICHA'ga murojaat (seni/sizni/тебя/you) + yaratish fe'li, yoki "yaratuvching" kabi ot; boshqa amal so'zi yo'q.
_CREATOR_NOUN = re.compile(
    r"\b(?:yaratuvching|yaratuvchingiz|yaratuvchisi kim|muallifing|muallifingiz)\b|яратувчинг|муаллифинг|"
    r"(?:твой|ваш)\s+(?:создатель|автор|разработчик)|\byour\s+(?:creator|developer|author|maker)\b", re.I)
_CREATOR_YOU = re.compile(r"\b(?:seni|sani|sizni|сени|сизни|тебя|вас|you)\b", re.I)
_CREATOR_VERB = re.compile(
    r"\b(?:yarat\w*|yasa\w*|tuzgan|ishlab chiq\w*|o'ylab top\w*|яратг\w*|яратд\w*|ясаг\w*|тузган|"
    r"создал\w*|сделал\w*|разработал\w*|придумал\w*|created|made|built|developed|designed)", re.I)


class _CreatorQuestion:
    """Yaratuvchi haqidagi savolni aniqlaydi (re.Pattern'ga o'xshash .search interfeysi)."""

    @staticmethod
    def search(low: str) -> bool:
        if _CREATOR_NOUN.search(low):
            return True
        if not (_CREATOR_YOU.search(low) and _CREATOR_VERB.search(low)):
            return False
        rest = _CREATOR_VERB.sub(" ", low)
        return not _ACTION_WORDS.search(rest)   # "seni kim yaratgan? papka yarat" — buyruq bor, suhbat emas


CREATOR_QUESTION = _CreatorQuestion()


def _mentions_app(low: str) -> bool:
    """Ilova nomi tilga olingan gap (Telegram, Safari, Notes…) — buyruq bo'lishi mumkin, suhbat emas."""
    from .providers.rule_based import APP_ALIASES, KNOWN_APPS

    words = set(re.findall(r"\w+", low))
    names = {a.lower() for a in KNOWN_APPS} | {a.lower() for a in APP_ALIASES}
    return any(n in words or (" " in n and n in low) for n in names)


def detect_chat(text: str) -> bool:
    """Oddiy suhbatmi (amal so'ralmagan)? Shubha bo'lsa — False (buyruq yo'lida qoladi)."""
    t = re.sub(r"[ʻ’‘`´]", "'", text).strip()
    low = t.lower().strip(" .!,")
    if not low or _SCREEN_WORDS.search(low) or _mentions_app(low):
        return False
    if CREATOR_QUESTION.search(low):
        return True
    if _ACTION_WORDS.search(low):
        return False
    if _CHAT_PATTERNS.search(low) or _SHORT_REACTION.match(low):
        return True
    # Umumiy savol ("Samarqand qayerda?", "Python nima?") — amal so'zisiz
    return t.endswith("?") or bool(_QUESTION_START.match(low))


def _clean_query(q: str) -> str:
    q = re.sub(r"[ʻ’‘`´]", "'", q).strip(" .!?\"'«»")
    q = re.sub(r"^(?:menga|iltimos|please|пожалуйста)\s+", "", q, flags=re.I)
    return q.strip()


def detect_search(text: str) -> str | None:
    if _BROWSER.search(text):
        return None   # "Googleda qidir" — brauzerda ochish (mavjud tezkor yo'l)
    t = text.strip().rstrip(".!?")
    for p in _SEARCH:
        m = p.match(t)
        if m:
            q = _clean_query(m.group("q"))
            if q and not _PRONOUN.match(q):
                return q
    return None


def detect_file(text: str) -> str | None:
    t = re.sub(r"[ʻ’‘`´]", "'", text.strip().rstrip(".!?"))
    for p in _FILE:
        m = p.match(t)
        if m:
            return _clean_query(m.group("q"))
    return None


def route(text: str, language: str, conversation: Conversation | None = None, fast_path: bool = True) -> Route:
    resolved_from = ""
    if conversation is not None:
        res = conversation.resolve(text, language)
        if res.action is not None:
            act = Action.model_validate(res.action)
            if act.type == "reveal":
                reply = _REVEALED.get(language, _REVEALED["en"]).format(x=act.path.rsplit("/", 1)[-1])
            else:
                reply = parse_command(res.text, language)[2]
            return Route("tool" if act.type == "reveal" else "fast", res.kind, [act], reply, text, res.note,
                         ref=res.kind)
        if res.kind == "repeat":
            resolved_from, text = text, res.text
            r = route(text, language, None, fast_path)
            r.resolved_from, r.ref = resolved_from, "repeat"
            return r

    fq = detect_file(text)
    if fq is not None:
        if _PRONOUN.match(fq) or not fq:
            if conversation is not None and conversation.last_path:
                p = conversation.last_path
                return Route("tool", "reveal", [Action(type="reveal", path=p)],
                             _REVEALED.get(language, _REVEALED["en"]).format(x=p.rsplit("/", 1)[-1]), text, ref="last_path")
            return Route("clarify", "find_file", reply=_NEED_NAME.get(language, _NEED_NAME["en"]))
        return Route("tool", "find_file", [Action(type="find_file", text=fq)], "", resolved_from)

    sq = detect_search(text)
    if sq is not None:
        return Route("tool", "web_search", [Action(type="web_search", text=sq)], "", resolved_from)

    if detect_chat(text):
        return Route("chat", "chat", resolved_from=resolved_from)

    if fast_path:
        intent, actions, reply = parse_command(text, language)
        if intent == "system" and actions:
            return Route("fast", intent, actions, reply, resolved_from)
        if is_simple(text) and intent in FAST_INTENTS and len(actions) == 1:
            return Route("fast", intent, actions, reply, resolved_from)
    r = Route("autonomous", resolved_from=resolved_from)
    r.note = text   # (takrorlash bo'lsa) modelga beriladigan matn
    return r
