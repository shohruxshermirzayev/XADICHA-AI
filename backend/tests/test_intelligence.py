"""Til aniqlash, suhbat konteksti, marshrutlash, vositalar (qidiruv, fayl), qayta urinish siyosati, vaqt izi, ovoz.

Hammasi SIMULYATSIYA: tarmoq so'rovlari soxta (namunaviy HTML/JSON), adapter — dry-run, model — skriptlangan.
"""

from __future__ import annotations

import time

import pytest
from conftest import ScriptedProvider, api_client

from xadicha.adapters.base import DryRunAdapter, ExecResult
from xadicha.agent import Agent
from xadicha.conversation import Conversation
from xadicha.lang import detect_text_language, refine_asr_language
from xadicha.models import Action, StepStatus, TaskStatus
from xadicha.router import route
from xadicha.service import XadichaService
from xadicha.speech.stt import Endpointer, pick_language
from xadicha.speech.tts import choose_mac_voice, speech_text
from xadicha.tools import search as S
from xadicha.tools.files import find_files

# ---------------------------------------------------------------- til aniqlash

@pytest.mark.parametrize("text,selected,lang", [
    ("Safari ni och", "en", "uz"), ("Safarini och", "ru", "uz"), ("Ekranda nima turganini ayt", "en", "uz"),
    ("Google dan Python haqida qidir", "en", "uz"), ("open calculator", "uz", "en"), ("what is on my screen", "uz", "en"),
    ("Сафари ни оч", "ru", "uz"), ("Телеграмни оч", "ru", "uz"), ("Ҳисобот папкасини яратинг", "ru", "uz"),
    ("Открой Notes", "uz", "ru"), ("найди погоду в Ташкенте", "uz", "ru"), ("Safari", "uz", "uz"), ("Safari", "en", "en"),
])
def test_text_language_detection(text, selected, lang):
    assert detect_text_language(text, selected).lang == lang


def test_latin_is_not_assumed_uzbek_and_cyrillic_not_assumed_russian():
    assert detect_text_language("Open Safari please", "uz").lang == "en"
    assert detect_text_language("Сафари ни оч", "ru").lang == "uz"


def test_asr_language_is_refined_only_on_strong_signal():
    assert refine_asr_language("Сафари ни оч", "ru", 0.6, "uz") == "uz"
    assert refine_asr_language("Открой Notes", "ru", 0.9, "uz") == "ru"       # tanlangan til — faqat prior
    assert refine_asr_language("Safari", "en", 0.95, "uz") == "en"           # neytral matn — ASR'ga ishoniladi


def test_language_prior_does_not_override_clear_other_language():
    assert pick_language([("ru", 0.7), ("uz", 0.2)], "ru", prior="uz")[0] == "ru"
    assert pick_language([("ru", 0.4), ("uz", 0.35)], "ru", prior="uz")[0] == "uz"   # yaqin bo'lsa — prior


# ---------------------------------------------------------------- marshrutlash va o'zbek korpusi

@pytest.mark.parametrize("text,path,first", [
    ("Safari ni och", "fast", ("open_app", "Safari")), ("Safarini och", "fast", ("open_app", "Safari")),
    ("Safari ochib ber", "fast", ("open_app", "Safari")), ("Safari ga kir", "fast", ("open_app", "Safari")),
    ("Brauzerni ishga tushir", "fast", ("open_app", "Safari")),
    ("Google dan Python haqida qidir", "fast", ("open_url", "https://www.google.com/search?q=Python")),
    ("YouTube'da o'zbek musiqasini qidir", "fast", ("open_url", "https://www.youtube.com/results?search_query=o%27zbek+musiqasini")),
    ("Python haqida qidir", "tool", ("web_search", "Python")),
    ("найди информацию о Самарканде", "tool", ("web_search", "Самарканде")),
    ("search for uzbek history", "tool", ("web_search", "uzbek history")),
    ("hisobot faylini top", "tool", ("find_file", "hisobot")), ("find file report", "tool", ("find_file", "report")),
    ("ovozni ko'tar", "fast", ("system", "volume_up")),
    ("Ekranda nima turganini ayt", "autonomous", None),
])
def test_routing(text, path, first):
    r = route(text, "uz", Conversation())
    assert r.path == path, r
    if first:
        a = r.actions[0]
        assert (a.type, a.app or a.url or a.text or a.control) == first


def test_file_reference_without_context_asks_for_name():
    r = route("Shu faylni topib ber", "uz", Conversation())
    assert r.path == "clarify" and "Qaysi faylni" in r.reply


def _conv():
    c = Conversation()
    c.last_app, c.last_instruction, c.last_lang = "Safari", "Telegram ni och", "uz"
    c.last_results = [{"title": "Python", "url": "https://python.org"}, {"title": "PEP 8", "url": "https://peps.python.org/pep-0008/"}]
    c.last_path = "/tmp/ws/Hisobot"
    return c


@pytest.mark.parametrize("text,lang,expected", [
    ("uni yana och", "uz", ("open_app", "Safari")), ("открой его снова", "ru", ("open_app", "Safari")),
    ("open it again", "en", ("open_app", "Safari")), ("birinchisini och", "uz", ("open_url", "https://python.org")),
    ("открой второй", "ru", ("open_url", "https://peps.python.org/pep-0008/")),
    ("shu papkani ko'rsat", "uz", ("reveal", "/tmp/ws/Hisobot")), ("show that file", "en", ("reveal", "/tmp/ws/Hisobot")),
])
def test_follow_up_references(text, lang, expected):
    r = route(text, lang, _conv())
    a = r.actions[0]
    assert (a.type, a.app or a.url or a.path) == expected and r.resolved_from == text


def test_repeat_last_command():
    r = route("yana bir marta", "uz", _conv())
    assert r.path == "fast" and r.actions[0].app == "Telegram" and r.resolved_from == "yana bir marta"


def test_conversation_is_bounded_and_redacted():
    c = Conversation()
    for i in range(50):
        c.add_user(f"buyruq {i} token=supersecret123", "uz")
    assert len(c.turns) == 20 and "supersecret123" not in c.summary()


# ---------------------------------------------------------------- internet qidiruvi (namunaviy javoblar)

DDG_HTML = """
<div class="result results_links results_links_deep web-result result--ad"><a class="result__a" href="https://ads.example/x">Ad</a></div>
<div class="result results_links results_links_deep web-result ">
  <h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F&amp;rut=abc">Welcome to <b>Python</b>.org</a></h2>
  <a class="result__snippet" href="x">The official home of the <b>Python</b> Programming Language.</a>
</div>
<div class="result results_links web-result ">
  <h2 class="result__title"><a class="result__a" href="https://en.wikipedia.org/wiki/Python_(programming_language)">Python (programming language) - Wikipedia</a></h2>
  <a class="result__snippet" href="y">Python is a high-level, general-purpose programming language.</a>
</div>
"""


def test_ddg_parser_extracts_real_urls_and_skips_ads():
    res = S.parse_ddg_html(DDG_HTML)
    assert [r.url for r in res] == ["https://www.python.org/", "https://en.wikipedia.org/wiki/Python_(programming_language)"]
    assert res[0].title == "Welcome to Python.org" and "official home" in res[0].snippet


def test_ddg_captcha_is_reported_not_hidden():
    with pytest.raises(S.SearchError) as e:
        S.parse_ddg_html('<div class="anomaly-modal">Unfortunately, bots use DuckDuckGo too</div>')
    assert e.value.kind == "captcha"


def test_wikipedia_parser():
    data = {"query": {"search": [{"title": "Samarqand", "snippet": "<span>Samarqand</span> — shahar", "timestamp": "2026-01-02T00:00:00Z"}]}}
    r = S.parse_wikipedia(data, "uz")[0]
    assert r.url == "https://uz.wikipedia.org/wiki/Samarqand" and r.snippet == "Samarqand — shahar" and r.date == "2026-01-02"


def test_rank_dedupes_and_prefers_matching():
    rs = [S.SearchResult("Other", "https://a.com"), S.SearchResult("Python docs", "https://b.com"),
          S.SearchResult("Python docs", "https://b.com/")]
    out = S.rank(rs, "python docs")
    assert [r.url for r in out] == ["https://b.com", "https://a.com"]


class _Resp:
    def __init__(self, status, text="", js=None):
        self.status_code, self.text, self._js = status, text, js

    def json(self):
        return self._js


def test_web_search_falls_back_and_reports_errors():
    def ddg_captcha(q, lang, timeout=8):
        raise S.SearchError("captcha")

    def wiki_ok(q, lang, timeout=8):
        return [S.SearchResult("Samarqand", "https://uz.wikipedia.org/wiki/Samarqand", "shahar", "wikipedia")]

    res, provider, errors = S.web_search("Samarqand", "uz", [ddg_captcha, wiki_ok])
    assert provider == "wiki_ok" and res and errors == ["ddg_captcha:captcha"]
    res, provider, errors = S.web_search("x", "uz", [ddg_captcha])
    assert res == [] and provider == ""


def test_ddg_http_errors_are_classified():
    with pytest.raises(S.SearchError) as e:
        S.search_ddg("x", "uz", fetch=lambda *a, **k: _Resp(429))
    assert e.value.kind == "captcha"
    assert S.search_ddg("python", "en", fetch=lambda *a, **k: _Resp(200, DDG_HTML))[0].url == "https://www.python.org/"


# ---------------------------------------------------------------- agent: vosita yo'li

class SummaryProvider(ScriptedProvider):
    name = "ollama"

    def complete(self, system, user, screen):
        assert "ONLY" in system and "[1]" in user
        return '{"answer": "Python — dasturlash tili [1]."}'


def _agent(cfg, storage, provider=None, results=None):
    cfg.fast_path = True
    ag = Agent(cfg, provider or ScriptedProvider(), DryRunAdapter(), storage)
    ag.conversation = Conversation()
    ag.search_fn = lambda q, lang: (results if results is not None else
                                    [S.SearchResult("Welcome to Python.org", "https://www.python.org/", "official", "duckduckgo")],
                                    "ddg" if results != [] else "", [] if results != [] else ["search_ddg:network"])
    return ag


def test_search_answer_is_based_on_results_with_sources(cfg, storage):
    ag = _agent(cfg, storage, SummaryProvider())
    t = ag.run("Python haqida qidir", "uz")
    assert t.status == TaskStatus.success and t.planner == "tool" and t.final_message == "Python — dasturlash tili [1]."
    assert t.data["results"][0]["url"] == "https://www.python.org/" and t.llm_calls == 1


def test_search_without_llm_lists_real_titles(cfg, storage):
    t = _agent(cfg, storage).run("search for python", "en")
    assert t.final_message.startswith("Results found:") and "Welcome to Python.org" in t.final_message


def test_search_failure_is_admitted(cfg, storage):
    t = _agent(cfg, storage, results=[]).run("Python haqida qidir", "uz")
    assert t.status == TaskStatus.failed and "Qidiruv ishlamadi" in t.final_message


def test_follow_up_opens_first_search_result(cfg, storage):
    ag = _agent(cfg, storage)
    t1 = ag.run("Python haqida qidir", "uz")
    ag.conversation.add_task(t1)
    t2 = ag.run("birinchisini och", "uz")
    assert t2.resolved_from == "birinchisini och" and ag.adapter.executed[-1].url == "https://www.python.org/"


def test_find_file_then_reveal_it(cfg, storage, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Hisobot-2026.pdf").write_text("x")
    cfg.workspace = tmp_path
    ag = _agent(cfg, storage)
    t1 = ag.run("hisobot faylini top", "uz")
    assert t1.status == TaskStatus.success and t1.data["results"][0]["title"] == "Hisobot-2026.pdf"
    ag.conversation.add_task(t1)
    t2 = ag.run("shu faylni ko'rsat", "uz")
    assert ag.adapter.executed[-1].type == "reveal" and ag.adapter.executed[-1].path.endswith("Hisobot-2026.pdf")


def test_file_search_stays_in_workspace_and_skips_sensitive(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "report_key").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "report.js").write_text("x")
    (tmp_path / "report.txt").write_text("x")
    assert [p.name for p in find_files("report", tmp_path)] == ["report.txt"]


def test_reveal_outside_workspace_is_blocked(tmp_path):
    from xadicha import safety

    assert safety.blocked_reason(Action(type="reveal", path="/etc/hosts"), tmp_path)
    assert safety.blocked_reason(Action(type="web_search", text=""), tmp_path)


# ---------------------------------------------------------------- qayta urinish siyosati, vaqt chegarasi, iz

def test_failed_non_idempotent_action_is_not_repeated_blindly(cfg, storage):
    same = {"action": {"type": "type_text", "text": "salom"}}
    p = ScriptedProvider([same, {**same, "previous_step_ok": False}, {**same, "previous_step_ok": False},
                          {**same, "previous_step_ok": False}])
    ad = DryRunAdapter(fail_types={"type_text"})
    t = Agent(cfg, p, ad, storage).run("salom deb yoz")
    assert len(ad.executed) == 1                      # faqat birinchi urinish bajarildi
    assert any("takrorlanmaydi" in s.detail for s in t.steps) and t.status == TaskStatus.failed


class SlowAdapter(DryRunAdapter):
    def execute(self, action):
        time.sleep(3)
        return ExecResult(True, "kech")


def test_adapter_call_times_out(cfg, storage, monkeypatch):
    from xadicha import models

    monkeypatch.setitem(models.TOOL_REGISTRY, "open_app", models.ToolSpec(read_only=False, idempotent=True, timeout_s=0.2,
                                                                          verify="frontmost_app"))
    p = ScriptedProvider([{"action": {"type": "open_app", "app": "Notes"}}, {"done": True, "success": False}])
    t = Agent(cfg, p, SlowAdapter(), storage).run("Notes")
    assert t.steps[0].status == StepStatus.failed and "vaqt tugadi" in t.steps[0].detail


def test_trace_records_stages_without_content(cfg, storage):
    p = ScriptedProvider([{"action": {"type": "open_app", "app": "Notes"}}, {"previous_step_ok": True, "done": True, "success": True}])
    t = Agent(cfg, p, DryRunAdapter(), storage).run("menga maxfiy narsani och")
    stages = [x["stage"] for x in t.trace]
    assert "route" in stages and "llm:decide" in stages and "exec:open_app" in stages
    assert "maxfiy" not in str(t.trace)
    assert t.steps[0].verification == "frontmost_app"


# ---------------------------------------------------------------- xizmat: suhbat saqlanadi va tiklanadi

def test_conversation_persists_across_restart_and_resolves_reference(cfg, storage):
    cfg.fast_path = True
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    svc.run_task("Telegram ni och", "uz", speak=False)
    svc2 = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    assert [t["role"] for t in svc2.conversation_public()["turns"]] == ["user", "assistant"]
    svc2.run_task("uni yana och", "uz", speak=False)
    assert svc2.adapter.executed[-1].app == "Telegram"


def test_conversation_api_and_new_session(cfg, storage):
    cfg.fast_path = True
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)
    client = api_client(svc)
    svc.run_task("Notes ni och", "uz", speak=False)
    c = client.get("/api/conversation").json()
    assert len(c["turns"]) == 2 and c["turns"][1]["task_id"]
    sid = client.post("/api/conversation/new").json()["session_id"]
    assert sid != c["session_id"] and client.get("/api/conversation").json()["turns"] == []
    assert svc.conversation.last_app is None   # yangi suhbatda eski kontekst yo'q


# ---------------------------------------------------------------- ovoz chiqarish va nutq tugashi

def test_speech_text_keeps_display_text_separate():
    s = speech_text("Ovoz 40% ga o'rnatildi. https://www.python.org/doc [1] Fayl ~/Desktop/a/rep.txt", "uz")
    assert s == "Ovoz 40 foiz ga oʻrnatildi. python nuqta org Fayl rep.txt"
    assert speech_text("it's report.pdf", "en") == "it's report.pdf"   # inglizchada apostrof va fayl nomi buzilmaydi


def test_voice_selection_never_reads_uzbek_with_foreign_voice():
    installed = {"Samantha": "en_US", "Milena": "ru_RU", "Yuri": "ru_RU"}
    assert choose_mac_voice("uz", None, installed) is None
    assert choose_mac_voice("ru", None, installed) == "Milena"
    assert choose_mac_voice("en", "Ava", installed) == "Samantha"     # sozlangan ovoz o'rnatilmagan → afzal ro'yxat


def _feed(ep, seq, dt=0.032):
    t = 0.0
    for level, dur in seq:
        for _ in range(int(dur / dt)):
            t += dt
            if ep.feed(level, dt):
                return t
    return None


def test_endpointer_tolerates_pause_inside_long_sentence():
    ep = Endpointer()
    # 2 s gapirdi, 1.0 s o'ylab turdi, yana gapirdi — 1.0 s pauza kesib qo'ymasligi kerak
    stop = _feed(ep, [(0.004, 0.3), (0.1, 2.0), (0.004, 1.0), (0.1, 0.8), (0.004, 3.0)])
    assert stop is not None and stop > 4.0 and ep.reason == "silence"


def test_endpointer_hysteresis_keeps_quieter_word_endings():
    ep = Endpointer()
    # boshlanish 0.1, so'z oxiri 0.02 (on-chegaradan past, off-chegaradan yuqori) — nutq davom etadi
    stop = _feed(ep, [(0.005, 0.3), (0.1, 0.5), (0.02, 0.6), (0.005, 2.0)])
    assert stop is not None and stop > 0.3 + 0.5 + 0.6


def test_endpointer_adapts_when_noise_rises_before_speech():
    ep = Endpointer()
    stop = _feed(ep, [(0.004, 0.3), (0.012, 2.0), (0.004, 5.0)])   # fan yoqildi (shovqin oshdi), nutq yo'q
    assert ep.reason == "no_speech" and stop is not None


def test_endpoint_delay_is_measured():
    ep = Endpointer()
    _feed(ep, [(0.004, 0.3), (0.1, 0.6), (0.004, 2.0)])
    assert 0.85 <= ep.endpoint_delay_s <= 1.0


# ---------------------------------------------------------------- korpus: til, niyat, obyekt (matn, ASR'siz)

def test_manifest_corpus_has_30_command_types_in_all_languages():
    from xadicha.speech_eval import load_manifest

    rows = load_manifest()
    types = {r["command_type"] for r in rows}
    assert len(types) >= 30
    for t in types:
        langs = {r["lang"] for r in rows if r["command_type"] == t}
        assert {"uz", "ru", "en"} <= langs, t
    assert any(r["script"] == "cyrl" and r["lang"] == "uz" for r in rows)


def test_text_understanding_regressions_on_corpus():
    # Bu korpusda topilgan xatolar qaytmasligi uchun: aralash yozuv ("Открой Safari"), savol, havola, kirill nom
    from xadicha.speech_eval import load_manifest, text_eval

    s, _ = text_eval(load_manifest())
    assert s["errors"] == [], s["errors"]


def test_delete_with_filename_is_never_turned_into_reveal():
    r = route("Delete the file eslatma.txt", "en", _conv())
    assert r.path == "autonomous" and not r.resolved_from
    r = route("eslatma.txt faylini o'chir", "uz", _conv())
    assert r.path == "autonomous"


def test_question_is_not_parsed_as_open_command():
    assert route("Which app is open right now?", "en", Conversation()).path == "autonomous"
