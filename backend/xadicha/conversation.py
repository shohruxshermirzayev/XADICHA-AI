"""Suhbat konteksti: chegaralangan, sessiyaga bog'liq, maxfiylikni hisobga olgan xotira.

Nimani eslaydi: oxirgi navbatlar (buyruq va javob matni, maks. 20) va ular ichidan obyektlar — oxirgi ochilgan
ilova, sayt, fayl yo'li, qidiruv so'rovi va natijalari. Nimani eslamaydi: ekran surati, OCR matni, clipboard.
Matnlar `redact()` dan o'tadi (kalit, token, parol). "Yangi suhbat" barcha kontekstni tozalaydi.

Havolalarni hal qilish (qoida asosida): "uni yana och", "открой его снова", "open it again", "birinchisini och",
"shu faylni ko'rsat", "yana bir marta" — oxirgi obyektga aylantiriladi. Hal qilingan matn asl matndan alohida saqlanadi.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_TURNS = 20
MAX_TEXT = 300


def _redact(text: str) -> str:
    from .service import redact   # aylanma importdan qochish uchun kech import

    return redact(text)


@dataclass
class Turn:
    role: str                 # "user" | "assistant"
    text: str
    lang: str = ""
    task_id: str | None = None
    status: str | None = None
    ts: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Resolution:
    text: str                  # hal qilingan matn (ko'rsatish va model uchun)
    original: str
    kind: str = ""             # "" | repeat | last_app | last_url | last_path | result_n
    note: str = ""
    action: dict[str, Any] | None = None   # to'g'ridan-to'g'ri harakat (bo'lsa): {"type": ..., ...}


# "uni / shuni / o'shani / buni"
_IT_UZ = r"(?:uni|shuni|o'shani|buni|ani|уни|шуни|ўшани|буни)"
_AGAIN = r"(?:yana|qayta|qaytadan|яна|қайта|снова|опять|ещё раз|еще раз|again)"
_OPEN = r"(?:och|ochib ber|oching|ochgin|оч|очиб бер|открой|открыть|open|launch)"
_SHOW = r"(?:ko'rsat\w*|och\w*|top\w*|кўрсат\w*|оч\w*|топ\w*|покажи|открой|найди|show|open|find|reveal)"
_FILENAME = re.compile(r"\b[\w\-]+\.[a-z0-9]{2,5}\b", re.I)
_ORD = {
    "birinchi": 1, "ikkinchi": 2, "uchinchi": 3, "первый": 1, "первую": 1, "второй": 2, "вторую": 2,
    "третий": 3, "третью": 3, "first": 1, "second": 2, "third": 3, "1": 1, "2": 2, "3": 3,
}


class Conversation:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.turns: deque[Turn] = deque(maxlen=MAX_TURNS)
        self.last_instruction = ""
        self.last_lang = ""
        self.last_app: str | None = None
        self.last_url: str | None = None
        self.last_path: str | None = None
        self.last_query: str | None = None
        self.last_results: list[dict[str, Any]] = []   # [{title, url} | {path}]

    # --- yozish ---
    def add_user(self, text: str, lang: str) -> Turn:
        t = Turn("user", _redact(text)[:MAX_TEXT], lang)
        self.turns.append(t)
        return t

    def add_task(self, task: Any) -> Turn:
        """Bajarilgan vazifadan javob va obyektlarni oladi (faqat haqiqatan bajarilgan qadamlardan)."""
        if task.instruction and not re.fullmatch(rf"(?:{_AGAIN}(?: bir marta)?)", task.instruction.strip().lower()):
            self.last_instruction, self.last_lang = task.instruction, task.language
        for s in task.steps:
            if s.status.value not in ("executed", "verified"):
                continue
            a = s.action
            if a.type == "open_app" and a.app:
                self.last_app = a.app
            elif a.type == "open_url" and a.url:
                self.last_url = a.url
            elif a.type in ("create_folder", "create_file", "reveal") and a.path:
                self.last_path = a.path
            elif a.type in ("web_search", "find_file") and a.text:
                self.last_query = a.text
        results = (getattr(task, "data", None) or {}).get("results")
        if results:
            self.last_results = [{k: r.get(k) for k in ("title", "url", "path") if r.get(k)} for r in results][:10]
            first = self.last_results[0]
            if first.get("path"):
                self.last_path = first["path"]
        t = Turn("assistant", _redact(task.final_message or "")[:MAX_TEXT], task.language, task.id, task.status.value)
        self.turns.append(t)
        return t

    def clear(self) -> None:
        self.__init__()

    # --- o'qish ---
    def summary(self, max_turns: int = 6) -> str:
        """Model uchun qisqa kontekst (oxirgi navbatlar + obyektlar). Ekran yoki shaxsiy fayl tarkibi yo'q."""
        lines = [f"{'User' if t.role == 'user' else 'Assistant'}: {t.text}" for t in list(self.turns)[-max_turns:]]
        facts = []
        if self.last_app:
            facts.append(f"last opened app: {self.last_app}")
        if self.last_url:
            facts.append(f"last opened URL: {self.last_url}")
        if self.last_path:
            facts.append(f"last file/folder: {self.last_path}")
        if self.last_query:
            facts.append(f"last search query: {self.last_query}")
        if facts:
            lines.append("Known context: " + "; ".join(facts))
        return "\n".join(lines)

    def resolve(self, text: str, lang: str = "uz") -> Resolution:
        """Havolani oxirgi obyektga aylantiradi. Hal qilib bo'lmasa — matn o'zgarishsiz qaytadi."""
        low = re.sub(r"[ʻ’‘`´]", "'", text.lower()).strip(" .!?")
        # 1) "yana bir marta" / "ещё раз" / "again" / "do it again" — oxirgi buyruqni takrorlash
        if re.fullmatch(rf"(?:{_AGAIN}(?: bir marta)?|do it again|repeat|takrorla|повтори)", low) and self.last_instruction:
            return Resolution(self.last_instruction, text, "repeat", "oxirgi buyruq takrorlandi")
        # 2) N-chi natija: "birinchisini och", "открой первый", "open the first one/result"
        m = re.search(r"(birinchi|ikkinchi|uchinchi|первый|первую|второй|вторую|третий|третью|first|second|third)", low)
        if m and self.last_results and re.search(_OPEN + r"|ko'rsat|покажи|show", low):
            n = _ORD[m.group(1)]
            if n <= len(self.last_results):
                r = self.last_results[n - 1]
                if r.get("url"):
                    return Resolution(_open_url_text(r["url"], lang), text, "result_n",
                                      f"{n}-natija: {r.get('title', r['url'])}", {"type": "open_url", "url": r["url"]})
                if r.get("path"):
                    return Resolution(_reveal_text(r["path"], lang), text, "result_n", f"{n}-natija: {r['path']}",
                                      {"type": "reveal", "path": r["path"]})
        # 3) "shu faylni/papkani ko'rsat|och", "открой эту папку", "show that file" — faqat ko'rsatish/ochish/topish
        #    fe'li bilan va aniq fayl nomi aytilmagan bo'lsa ("Delete the file x.txt" bu yerga TUSHMAYDI)
        if self.last_path and not _FILENAME.search(low) and re.search(_SHOW, low) and re.search(
                r"(?:shu|o'sha|bu|шу|ўша|бу)\s+(?:fayl|papka|hujjat|файл|папка|ҳужжат)\w*"
                r"|(?:этот|эту|тот|ту)\s+(?:файл|папку)|(?:that|this)\s+(?:file|folder)", low):
            return Resolution(_reveal_text(self.last_path, lang), text, "last_path", self.last_path,
                              {"type": "reveal", "path": self.last_path})
        # 4) "o'sha saytni och", "открой этот сайт", "open that site"
        if self.last_url and re.search(_SHOW, low) and re.search(
                r"(?:shu|o'sha|bu)\s+sayt\w*|(?:этот|тот)\s+сайт|(?:that|this)\s+(?:site|page|website)", low):
            return Resolution(_open_url_text(self.last_url, lang), text, "last_url", self.last_url,
                              {"type": "open_url", "url": self.last_url})
        # 5) "uni yana och", "открой его снова", "open it again", "reopen it"
        it = rf"(?:{_IT_UZ}|его|её|ее|это|it)"
        if self.last_app and (re.search(rf"\b{it}\b.*{_OPEN}|{_OPEN}.*\b{it}\b", low) or re.fullmatch(r"reopen(?: it)?", low)
                              or re.fullmatch(rf"{_AGAIN}\s+{_OPEN}|{_OPEN}\s+{_AGAIN}", low)):
            return Resolution(_open_app_text(self.last_app, lang), text, "last_app", self.last_app,
                              {"type": "open_app", "app": self.last_app})
        return Resolution(text, text)


def _open_app_text(app: str, lang: str) -> str:
    return {"ru": f"Открой {app}", "en": f"Open {app}"}.get(lang, f"{app} ni och")


def _open_url_text(url: str, lang: str) -> str:
    return {"ru": f"Открой сайт {url}", "en": f"Open the website {url}"}.get(lang, f"{url} saytini och")


def _reveal_text(path: str, lang: str) -> str:
    return f"⁣reveal:{path}"   # ichki belgi: router buni reveal harakatiga aylantiradi (matn sifatida bajarilmaydi)
