"""Internet qidiruvi — haqiqiy natijalar (sarlavha, manzil, parcha), hech qachon to'qib chiqarilmaydi.

Provayderlar (bepul, kalitsiz):
  - DuckDuckGo HTML (html.duckduckgo.com) — umumiy qidiruv;
  - Wikipedia API ({uz,ru,en}.wikipedia.org) — ensiklopedik ma'lumot, zaxira.
Faqat shu ikki xostga so'rov yuboriladi (SEARCH_HOSTS). Autentifikatsiya va CAPTCHA chetlab o'tilmaydi:
CAPTCHA sahifasi aniqlansa — "captcha" xatosi qaytariladi va keyingi provayder sinab ko'riladi.
Real tarmoqda sinalmagan (dev muhitida tashqi tarmoq yopiq); tahlilchi namunaviy HTML bilan testlangan.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

SEARCH_HOSTS = ("html.duckduckgo.com", "uz.wikipedia.org", "ru.wikipedia.org", "en.wikipedia.org")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) XADICHA-AI/0.2 (research prototype)"
DDG_REGION = {"uz": "wt-wt", "ru": "ru-ru", "en": "us-en"}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    date: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


class SearchError(Exception):
    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind          # network | captcha | empty | http


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_ddg_html(page: str) -> list[SearchResult]:
    if re.search(r"anomaly-modal|Unfortunately, bots use DuckDuckGo|challenge-form", page, re.I):
        raise SearchError("captcha", "DuckDuckGo CAPTCHA so'radi")
    out: list[SearchResult] = []
    starts = list(re.finditer(r'<div[^>]+class="([^"]*\bresult\b[^"]*)"', page))
    for i, st in enumerate(starts):
        if "result--ad" in st.group(1):
            continue   # reklama
        b = page[st.end(): starts[i + 1].start() if i + 1 < len(starts) else len(page)]
        a = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not a:
            continue
        href = html.unescape(a.group(1))
        if href.startswith("//"):
            href = "https:" + href
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:   # DuckDuckGo yo'naltirish havolasi → haqiqiy manzil
            href = unquote(q["uddg"][0])
        if not href.startswith(("http://", "https://")):
            continue
        sn = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>', b, re.S)
        out.append(SearchResult(_clean(a.group(2)), href, _clean(sn.group(1)) if sn else "", "duckduckgo"))
    return out


def parse_wikipedia(data: dict[str, Any], lang: str) -> list[SearchResult]:
    out = []
    for item in (data.get("query") or {}).get("search", []):
        title = item.get("title", "")
        url = f"https://{lang}.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"
        out.append(SearchResult(title, url, _clean(item.get("snippet", "")), "wikipedia",
                                (item.get("timestamp") or "")[:10] or None))
    return out


def rank(results: list[SearchResult], query: str, limit: int = 5) -> list[SearchResult]:
    """Takrorlarni olib tashlaydi va so'rov so'zlari sarlavha/parchada uchrashiga qarab tartiblaydi."""
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    seen, uniq = set(), []
    for r in results:
        key = r.url.split("#")[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    def score(i_r: tuple[int, SearchResult]) -> tuple[int, int]:
        i, r = i_r
        text = (r.title + " " + r.snippet).lower()
        return (-sum(t in text for t in terms), i)   # mos so'zlar ko'p → yuqorida; teng bo'lsa asl tartib

    return [r for _, r in sorted(enumerate(uniq), key=score)][:limit]


Fetch = Callable[..., requests.Response]


def search_ddg(query: str, lang: str, timeout: float = 8.0, fetch: Fetch = requests.post) -> list[SearchResult]:
    try:
        r = fetch("https://html.duckduckgo.com/html/", data={"q": query, "kl": DDG_REGION.get(lang, "wt-wt")},
                  headers={"User-Agent": USER_AGENT}, timeout=timeout)
    except requests.RequestException as e:
        raise SearchError("network", f"DuckDuckGo: {e.__class__.__name__}") from e
    if r.status_code in (202, 403, 429):
        raise SearchError("captcha", f"DuckDuckGo HTTP {r.status_code}")
    if r.status_code != 200:
        raise SearchError("http", f"DuckDuckGo HTTP {r.status_code}")
    return parse_ddg_html(r.text)


def search_wikipedia(query: str, lang: str, timeout: float = 8.0, fetch: Fetch = requests.get) -> list[SearchResult]:
    wl = lang if lang in ("uz", "ru", "en") else "en"
    try:
        r = fetch(f"https://{wl}.wikipedia.org/w/api.php",
                  params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 5},
                  headers={"User-Agent": USER_AGENT}, timeout=timeout)
    except requests.RequestException as e:
        raise SearchError("network", f"Wikipedia: {e.__class__.__name__}") from e
    if r.status_code != 200:
        raise SearchError("http", f"Wikipedia HTTP {r.status_code}")
    return parse_wikipedia(r.json(), wl)


def web_search(query: str, lang: str = "uz", providers: list[Callable[..., list[SearchResult]]] | None = None,
               timeout: float = 8.0) -> tuple[list[SearchResult], str, list[str]]:
    """(natijalar, ishlagan provayder, xatolar). Natija bo'lmasa — bo'sh ro'yxat va xatolar sababi bilan."""
    providers = providers or [search_ddg, search_wikipedia]
    errors: list[str] = []
    t0 = time.time()
    for p in providers:
        left = max(2.0, timeout - (time.time() - t0))
        try:
            res = p(query, lang, timeout=left)
        except SearchError as e:
            errors.append(f"{p.__name__}:{e.kind}")
            continue
        if res:
            return rank(res, query), p.__name__.replace("search_", ""), errors
        errors.append(f"{p.__name__}:empty")
    return [], "", errors
