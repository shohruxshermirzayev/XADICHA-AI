"""5-qadam: real internet qidiruvi — natijalar haqiqiymi, manzillar ochiladimi, javob manbaga mosmi.

  python -m xadicha.validate search            # avtomatik tekshiruvlar
  python -m xadicha.validate search --judge    # + har javobni o'zingiz baholaysiz (tavsiya etiladi)

Javob ilovaning o'z kodi bilan tuziladi (agent._summarize_search) — sinov uchun alohida yo'l yo'q.
"""

from __future__ import annotations

import re
import statistics
import time
from typing import Any

from . import ask, save_result

QUERIES = [
    {"id": "uz_general_1", "lang": "uz", "type": "general", "query": "Samarqand tarixi"},
    {"id": "uz_general_2", "lang": "uz", "type": "general", "query": "Amir Temur qachon tug'ilgan"},
    {"id": "ru_general_1", "lang": "ru", "type": "general", "query": "Кто написал Бабурнаме"},
    {"id": "ru_general_2", "lang": "ru", "type": "general", "query": "Население Ташкента"},
    {"id": "en_general_1", "lang": "en", "type": "general", "query": "Who built the Registan in Samarkand"},
    {"id": "en_general_2", "lang": "en", "type": "general", "query": "Python programming language creator"},
    {"id": "uz_recent", "lang": "uz", "type": "recent", "query": "O'zbekiston yangiliklari bugun"},
    {"id": "ru_recent", "lang": "ru", "type": "recent", "query": "курс доллара в Узбекистане сегодня"},
    {"id": "en_recent", "lang": "en", "type": "recent", "query": "latest macOS version"},
    {"id": "site_kunuz", "lang": "uz", "type": "site", "query": "site:kun.uz dollar kursi"},
    {"id": "site_wiki", "lang": "en", "type": "site", "query": "site:en.wikipedia.org Ulugh Beg"},
    {"id": "nonsense", "lang": "uz", "type": "no_answer", "query": "qzxwv plorkt 77819 xadichanonexist"},
]
_STOP = {"which", "there", "their", "about", "these", "those", "haqida", "bilan", "uchun", "который", "которые",
         "также", "results", "result", "natijalar", "source", "sources", "manba", "manbalar"}


def check_url(url: str, timeout: float = 6.0) -> dict[str, Any]:
    import requests

    from ..tools.search import USER_AGENT

    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True, stream=True)
        r.close()
        return {"url": url, "status": r.status_code, "ok": r.status_code < 400, "final_url": r.url[:200]}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": None, "ok": False, "error": e.__class__.__name__}


def answer_checks(answer: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Javob tekshiruvi (sof funksiya): iqtiboslar mavjud natijalarga ishora qiladimi, javobdagi manzillar
    natijalardan olinganmi, javob so'zlarining qancha qismi natijalar matnida bor (leksik tayanch — taxminiy)."""
    n = min(5, len(results))
    cites = [int(c) for c in re.findall(r"\[(\d+)\]", answer)]
    urls = re.findall(r"https?://[^\s)\]]+", answer)
    known = {r.get("url", "").rstrip("/") for r in results}
    corpus = " ".join(f"{r.get('title', '')} {r.get('snippet', '')}" for r in results[:5]).lower()
    words = [w for w in re.findall(r"\w{5,}", re.sub(r"\[\d+\]", "", answer.lower())) if w not in _STOP]
    supported = [w for w in words if w in corpus or w[:6] in corpus]
    return {
        "citations": cites, "has_citation": bool(cites),
        "citations_valid": all(1 <= c <= n for c in cites) if cites else None,
        "invented_urls": [u for u in urls if u.rstrip("/.,") not in known],
        "lexical_support": round(len(supported) / len(words), 2) if words else None,
    }


def main(args) -> int:
    from ..adapters.base import DryRunAdapter
    from ..agent import Agent, msg
    from ..config import load_config
    from ..models import TaskRecord
    from ..providers import RuleBasedProvider, make_provider
    from ..tools.search import web_search

    cfg = load_config()
    try:
        provider = RuleBasedProvider() if args.no_summary else make_provider(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"Model yo'q ({e.__class__.__name__}) — faqat natijalar tekshiriladi.")
        provider = RuleBasedProvider()
    agent = Agent(cfg, provider, DryRunAdapter())
    items = []
    for q in QUERIES:
        print(f"\n[{q['id']}] «{q['query']}» ({q['lang']})")
        t0 = time.perf_counter()
        results, prov, errors = web_search(q["query"], q["lang"])
        search_ms = round((time.perf_counter() - t0) * 1000)
        res = [r.public() for r in results]
        rec: dict[str, Any] = {**q, "search_ms": search_ms, "provider": prov, "errors": errors, "n_results": len(res),
                               "results": res[:5]}
        if not res:
            only_empty = errors and all(e.endswith(":empty") for e in errors)
            rec["answer"] = msg("no_results" if only_empty else "search_failed", q["lang"])
            rec["honest_failure"] = True   # natija yo'q — javob to'qib chiqarilmadi, sababi aytildi
            print(f"   natija yo'q: {errors} → «{rec['answer']}»")
        else:
            rec["url_checks"] = [check_url(r["url"]) for r in res[:3]]
            task = TaskRecord(instruction=q["query"], language=q["lang"])
            task.data.update(query=q["query"], results=res)
            t1 = time.perf_counter()
            rec["answer"] = agent._summarize_search(task)
            rec["summary_ms"] = round((time.perf_counter() - t1) * 1000)
            rec["summarizer"] = provider.name
            rec["checks"] = answer_checks(rec["answer"], res)
            ok_urls = sum(1 for u in rec["url_checks"] if u["ok"])
            print(f"   {prov}: {len(res)} natija, {search_ms} ms · URL ochildi: {ok_urls}/{len(rec['url_checks'])}")
            for i, r in enumerate(res[:3], 1):
                print(f"     [{i}] {r['title'][:70]} — {r['url'][:80]}")
            print(f"   Javob: «{rec['answer']}»")
            if args.judge:
                rec["human_grounded"] = ask("   Javob yuqoridagi manbalarga mos va to'g'rimi?")
        items.append(rec)
    with_res = [r for r in items if r["n_results"]]
    url_checks = [u for r in with_res for u in r.get("url_checks", [])]
    judged = [r for r in with_res if "human_grounded" in r]
    summary = {
        "queries": len(items), "with_results": len(with_res),
        "by_provider": {p: sum(1 for r in with_res if r["provider"] == p) for p in {r["provider"] for r in with_res}},
        "failures": [{"id": r["id"], "errors": r["errors"]} for r in items if not r["n_results"]],
        "search_ms_median": round(statistics.median([r["search_ms"] for r in items])) if items else None,
        "summary_ms_median": (round(statistics.median([r["summary_ms"] for r in with_res if "summary_ms" in r]))
                              if any("summary_ms" in r for r in with_res) else None),
        "url_valid_rate": round(100 * sum(u["ok"] for u in url_checks) / len(url_checks), 1) if url_checks else None,
        "answers_with_citation": sum(1 for r in with_res if r.get("checks", {}).get("has_citation")),
        "answers_with_invalid_citation": sum(1 for r in with_res if r.get("checks", {}).get("citations_valid") is False),
        "answers_with_invented_url": sum(1 for r in with_res if r.get("checks", {}).get("invented_urls")),
        "lexical_support_mean": (round(statistics.mean([r["checks"]["lexical_support"] for r in with_res
                                                       if r.get("checks", {}).get("lexical_support") is not None]), 2)
                                 if any(r.get("checks", {}).get("lexical_support") is not None for r in with_res) else None),
        "human_grounded_rate": round(100 * sum(r["human_grounded"] for r in judged) / len(judged), 1) if judged else None,
        "nonsense_query": next(({"n_results": r["n_results"], "answer": r["answer"]} for r in items if r["type"] == "no_answer"), None),
    }
    path = save_result("search", {"real": True, "kind": "real network search", "summarizer": provider.name,
                                  "summary": summary, "items": items})
    short = {k: summary[k] for k in ("queries", "with_results", "url_valid_rate", "answers_with_citation",
                                     "answers_with_invented_url", "human_grounded_rate", "search_ms_median")}
    print(f"\n{short}\nNatijasiz: {[f['id'] for f in summary['failures']]}\nSaqlandi: {path}")
    return 0
