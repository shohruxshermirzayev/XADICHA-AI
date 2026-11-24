"""Aqlli marshrutlash: buyruqni eng mos bajarish yo'liga yo'naltiradi.

  fast        — aniq, deterministik buyruq (ovoz/yorqinlik, ma'lum ilova, sayt, papka) → modelsiz, darhol
  tool        — maxsus vosita yetarli (internetdan qidirish, fayl qidirish, havola: "uni yana och")
  autonomous  — murakkab vazifa → LLM: ekran, reja, qadam-baqadam bajarish, tekshiruv, tiklanish
  clarify     — buyruqda zarur obyekt yo'q ("shu faylni top", lekin kontekstda fayl yo'q)

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
    path: str                       # fast | tool | autonomous | clarify
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

    if fast_path:
        intent, actions, reply = parse_command(text, language)
        if intent == "system" and actions:
            return Route("fast", intent, actions, reply, resolved_from)
        if is_simple(text) and intent in FAST_INTENTS and len(actions) == 1:
            return Route("fast", intent, actions, reply, resolved_from)
    r = Route("autonomous", resolved_from=resolved_from)
    r.note = text   # (takrorlash bo'lsa) modelga beriladigan matn
    return r
