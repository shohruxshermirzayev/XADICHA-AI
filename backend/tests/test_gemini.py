"""Gemini provayderi, Google Search grounding, Ollama zaxirasi va kalit xavfsizligi.

DIQQAT: bu testlar SIMULYATSIYA — tarmoqqa chiqmaydi. Gemini o'rniga soxta mijoz ishlatiladi, lekin javob va
xato obyektlari rasmiy `google-genai` SDK turlaridan (types.GenerateContentResponse, errors.ClientError) quriladi.
Haqiqiy API sinovi alohida: `python scripts/gemini_smoke.py` (kalit va internet kerak).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys

import pytest
from conftest import ScriptedProvider, api_client
from google.genai import errors, types

from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent
from xadicha.config import Config, load_config
from xadicha.models import Mode, TaskStatus
from xadicha.providers import make_provider
from xadicha.providers.base import LLMProvider, ProviderError
from xadicha.providers.fallback import FallbackProvider
from xadicha.providers.gemini_provider import GeminiProvider, classify_error
from xadicha.redaction import redact, register_secret, safe_env
from xadicha.router import needs_web
from xadicha.service import RedactFilter, XadichaService
from xadicha.vision.screen import Screenshot

FAKE_KEY = "AIzaSyFAKE-test-key-0123456789abcdefghijk"   # soxta, formati Google kalitiga o'xshaydi


# ---------- soxta Gemini mijozi (SDK turlari bilan) ----------

def response(text: str, grounding: dict | None = None, finish: str = "STOP") -> types.GenerateContentResponse:
    cand: dict = {"content": {"role": "model", "parts": [{"text": text}] if text else []}, "finish_reason": finish}
    if grounding is not None:
        cand["grounding_metadata"] = grounding
    return types.GenerateContentResponse.model_validate({"candidates": [cand]})


GROUNDING = {
    "web_search_queries": ["Gemini Live API latest"],
    "grounding_chunks": [
        {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA", "title": "ai.google.dev"}},
        {"retrieved_context": {"uri": "", "title": "ichki"}},           # URI'siz bo'lak — tashlanadi
        {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB", "title": "blog.google"}},
    ],
    "grounding_supports": [
        {"segment": {"start_index": 0, "end_index": 24, "text": "Gemini Live API yangilandi"},
         "grounding_chunk_indices": [0, 2]},
    ],
    "search_entry_point": {"rendered_content": "<style>.chip{}</style><a class='chip' href='https://www.google.com/search?q=x'>x</a>"},
}


def api_error(code: int, message: str, status: str, reason: str = "") -> errors.APIError:
    body = {"error": {"code": code, "message": message, "status": status,
                      "details": [{"reason": reason}] if reason else []}}
    return (errors.ServerError if code >= 500 else errors.ClientError)(code, body)


class FakeModels:
    def __init__(self, items=None, get_error: BaseException | None = None):
        self.items = list(items or [])
        self.calls: list[dict] = []
        self.get_error = get_error

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        # Ro'yxat tugasa — oxirgi xato takrorlanadi (server hali ham band)
        item = self.items.pop(0) if self.items else getattr(self, "last_error", None)
        if item is None:
            raise AssertionError("kutilmagan qo'shimcha so'rov")
        if isinstance(item, BaseException):
            self.last_error = item
            raise item
        return item

    def get(self, model):
        if self.get_error:
            raise self.get_error
        return {"name": f"models/{model}"}


class FakeClient:
    def __init__(self, items=None, get_error=None):
        self.models = FakeModels(items, get_error)


def gemini(items=None, **kw) -> GeminiProvider:
    kw.setdefault("retry_delay", 0)
    return GeminiProvider(FAKE_KEY, "gemini-test-model", client=FakeClient(items, kw.pop("get_error", None)), **kw)


class FakeOllama(LLMProvider):
    """Zaxira (Ollama o'rnida): olgan matnlarini yozib boradi."""

    name = "ollama"
    model = "qwen3.5:9b"
    supports_vision = True

    def __init__(self, reply: str | None = None, fail: bool = False):
        self.reply, self.fail, self.calls = reply, fail, []

    def complete(self, system, user, screen):
        self.calls.append({"system": system, "user": user, "screen": screen})
        if self.fail:
            raise ProviderError("Ollama bilan aloqa yo'q", kind="network")
        return self.reply or json.dumps({"reply": "Ollama javobi"})


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ---------- konfiguratsiya ----------

def test_config_reads_gemini_key_and_hides_it(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("XADICHA_PROVIDER", "gemini")
    monkeypatch.setenv("XADICHA_SEARCH_MODE", "AUTO")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    cfg = load_config()
    assert cfg.provider == "gemini" and cfg.gemini_api_key == FAKE_KEY
    assert cfg.search_mode == "auto" and cfg.gemini_model == "gemini-custom" and not cfg.warnings
    assert "GEMINI_API_KEY" not in os.environ            # subprocess'lar meros qilib olmaydi
    assert FAKE_KEY not in repr(cfg) and FAKE_KEY not in json.dumps(cfg.public())
    assert cfg.public()["has_api_key"] is True and cfg.public()["fallback"] == "ollama"
    assert load_config().gemini_api_key == FAKE_KEY       # qayta o'qilganda ham (xotiradan)


def test_unknown_provider_and_search_mode_are_reported_not_silent(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("XADICHA_PROVIDER", "gemni")
    monkeypatch.setenv("XADICHA_SEARCH_MODE", "sometimes")
    cfg = load_config()
    assert cfg.provider == "ollama" and cfg.search_mode == "auto"
    assert any("gemni" in w for w in cfg.warnings) and any("sometimes" in w for w in cfg.warnings)


@pytest.mark.parametrize("mode", ["auto", "always", "never"])
def test_search_modes_parsed(monkeypatch, mode):
    monkeypatch.setenv("XADICHA_SEARCH_MODE", mode)
    assert load_config().search_mode == mode


# ---------- provayder yaratish ----------

def test_make_provider_gemini_with_ollama_fallback(tmp_path):
    p = make_provider(Config(provider="gemini", gemini_api_key=FAKE_KEY, gemini_model="gemini-x", db_path=tmp_path / "d"))
    assert isinstance(p, FallbackProvider) and isinstance(p.primary, GeminiProvider)
    assert p.name == "gemini" and p.secondary.name == "ollama" and p.model == "gemini-x"


def test_make_provider_gemini_without_fallback(tmp_path):
    p = make_provider(Config(provider="gemini", gemini_api_key=FAKE_KEY, fallback="none", db_path=tmp_path / "d"))
    assert isinstance(p, GeminiProvider)


def test_missing_key_falls_back_to_ollama_with_clear_reason(tmp_path):
    p = make_provider(Config(provider="gemini", gemini_api_key="", db_path=tmp_path / "d"))
    assert isinstance(p, FallbackProvider) and p.primary is None
    assert p.name == "ollama"                              # "gemini ishlayapti" deb ko'rsatilmaydi
    assert "GEMINI_API_KEY" in p.info()["last_error"] and p.info()["using_fallback"] is True


def test_missing_key_without_fallback_raises():
    with pytest.raises(ProviderError) as e:
        GeminiProvider("", "gemini-x")
    assert e.value.kind == "config"


def test_other_providers_unchanged(tmp_path):
    from xadicha.providers.ollama_provider import OllamaProvider
    from xadicha.providers.rule_based import RuleBasedProvider

    assert isinstance(make_provider(Config(provider="ollama", db_path=tmp_path / "d")), OllamaProvider)
    assert isinstance(make_provider(Config(provider="mock", db_path=tmp_path / "d")), RuleBasedProvider)
    with pytest.raises(ProviderError):
        make_provider(Config(provider="claude", anthropic_api_key="", db_path=tmp_path / "d"))


# ---------- javobni qayta ishlash ----------

def test_complete_sends_system_json_and_image():
    g = gemini([response('{"intent": "open", "done": true, "final_message": "ok"}')])
    png = base64.b64encode(b"\x89PNG fake").decode()
    shot = Screenshot(png_base64=png, width=10, height=10, scale=1.0, media_type="image/png")
    d = g.decide("Safari ni och", [], shot, "uz")
    assert d.done and d.final_message == "ok"
    call = g._client.models.calls[0]
    cfg = call["config"]
    assert cfg.response_mime_type == "application/json" and "Uzbek" in cfg.system_instruction
    assert cfg.tools is None                                # qaror bosqichida qidiruv vositasi yo'q
    parts = call["contents"][0].parts
    assert parts[0].inline_data.mime_type == "image/png" and parts[0].inline_data.data == b"\x89PNG fake"
    assert "Safari ni och" in parts[1].text


def test_thought_parts_are_not_part_of_answer():
    r = types.GenerateContentResponse.model_validate({"candidates": [{"content": {"role": "model", "parts": [
        {"text": "ichki fikr", "thought": True}, {"text": '{"reply": "Javob"}'}]}, "finish_reason": "STOP"}]})
    assert gemini([r]).complete("s", "u", None) == '{"reply": "Javob"}'


def test_blocked_and_empty_responses():
    with pytest.raises(ProviderError) as e:
        gemini([response("", finish="SAFETY")]).complete("s", "u", None)
    assert e.value.kind == "blocked"
    with pytest.raises(ProviderError) as e:
        gemini([types.GenerateContentResponse.model_validate({"candidates": []})]).complete("s", "u", None)
    assert e.value.kind == "empty"


def test_thinking_config_dropped_once_if_model_rejects_it():
    err = api_error(400, "Thinking level is not supported for this model.", "INVALID_ARGUMENT")
    g = gemini([err, response('{"reply": "ok"}')], thinking="low")
    assert g.complete("s", "u", None) == '{"reply": "ok"}'
    calls = g._client.models.calls
    assert calls[0]["config"].thinking_config is not None and calls[1]["config"].thinking_config is None


# ---------- xato tasnifi ----------

@pytest.mark.parametrize("exc,kind", [
    (api_error(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT", "API_KEY_INVALID"), "auth"),
    (api_error(403, "Permission denied", "PERMISSION_DENIED"), "auth"),
    (api_error(404, "models/gemini-x is not found", "NOT_FOUND"), "config"),
    (api_error(429, "Resource exhausted", "RESOURCE_EXHAUSTED"), "quota"),
    (api_error(503, "The model is overloaded", "UNAVAILABLE"), "server"),
    (api_error(500, "Internal", "INTERNAL"), "server"),
])
def test_api_errors_classified(exc, kind):
    err = classify_error(exc)
    assert err.kind == kind and FAKE_KEY not in str(err)


def test_transport_errors_classified():
    import httpx

    assert classify_error(httpx.ReadTimeout("timed out")).kind == "timeout"
    assert classify_error(httpx.ConnectError("no route")).kind == "network"
    assert classify_error(ConnectionError("down")).kind == "network"


def test_invalid_key_message_is_clear_and_keyless():
    g = gemini([api_error(400, f"API key not valid: {FAKE_KEY}", "INVALID_ARGUMENT", "API_KEY_INVALID")])
    with pytest.raises(ProviderError) as e:
        g.complete("s", "u", None)
    assert e.value.kind == "auth" and "GEMINI_API_KEY" in str(e.value) and FAKE_KEY not in str(e.value)


def test_health_reports_invalid_key():
    g = gemini(get_error=api_error(400, "API key not valid", "INVALID_ARGUMENT", "API_KEY_INVALID"))
    ok, detail = g.health()
    assert not ok and "API kaliti" in detail


# ---------- grounding metadata ----------

def test_grounded_answer_parses_sources_queries_supports_and_suggestions():
    g = gemini([response("Gemini Live API yangilandi. Batafsil manbalarda.", GROUNDING)])
    a = g.grounded_answer("Gemini Live API eng yangi", "uz", "User: salom")
    cfg = g._client.models.calls[0]["config"]
    assert cfg.tools and cfg.tools[0].google_search is not None
    assert cfg.response_mime_type is None                   # grounding bosqichida JSON rejimi yo'q (alohida bosqich)
    assert a.grounded and a.text.startswith("Gemini Live API")
    assert [s["title"] for s in a.sources] == ["ai.google.dev", "blog.google"]
    assert a.sources[1]["url"].endswith("/BBB") and a.queries == ["Gemini Live API latest"]
    assert a.supports[0]["sources"] == [0, 1]               # URI'siz bo'lak tashlangani hisobga olingan
    assert "chip" in a.search_entry_point


def test_grounded_answer_without_metadata_is_not_marked_grounded():
    a = gemini([response("Javob")]).grounded_answer("savol", "en")
    assert not a.grounded and a.sources == [] and a.text == "Javob"


def test_always_mode_forces_search_instruction():
    g = gemini([response("x", GROUNDING)])
    g.grounded_answer("savol", "en", force=True)
    assert "MUST use Google Search" in g._client.models.calls[0]["config"].system_instruction


# ---------- zaxira (fallback) ----------

def test_fallback_on_gemini_error_keeps_same_context():
    clock = Clock()
    oll = FakeOllama('{"done": true, "final_message": "zaxira"}')
    fp = FallbackProvider(gemini([api_error(429, "quota", "RESOURCE_EXHAUSTED")]), oll, clock=clock)
    d = fp.decide("Notes ni och", [{"index": 1, "action": "open_app(Notes)", "status": "failed"}], None, "uz",
                  conversation="User: Safari ni och")
    assert d.final_message == "zaxira" and fp.name == "ollama"
    sent = oll.calls[0]
    assert "Notes ni och" in sent["user"] and "open_app(Notes)" in sent["user"] and "Safari ni och" in sent["user"]
    info = fp.info()
    assert info["active"] == "ollama" and info["using_fallback"] and info["last_error_kind"] == "quota"


@pytest.mark.parametrize("exc", [
    api_error(503, "overloaded", "UNAVAILABLE"),
    api_error(400, "API key not valid", "INVALID_ARGUMENT", "API_KEY_INVALID"),
])
def test_fallback_for_server_and_auth_errors(exc):
    oll = FakeOllama()
    fp = FallbackProvider(gemini([exc]), oll, clock=Clock())
    assert json.loads(fp.complete("s", "u", None))["reply"] == "Ollama javobi"


def test_fallback_on_timeout():
    import httpx

    oll = FakeOllama()
    fp = FallbackProvider(gemini([httpx.ReadTimeout("t")]), oll, clock=Clock())
    fp.complete("s", "u", None)
    assert fp.info()["last_error_kind"] == "timeout"


def test_cooldown_then_primary_retried():
    clock = Clock()
    g = gemini([api_error(504, "x", "DEADLINE_EXCEEDED"), response('{"reply": "gemini qaytdi"}')], clock=clock)
    oll = FakeOllama()
    fp = FallbackProvider(g, oll, clock=clock)
    fp.complete("s", "u", None)
    fp.complete("s", "u", None)                             # cooldown — Gemini chaqirilmaydi
    assert len(g._client.models.calls) == 1 and len(oll.calls) == 2
    clock.t += 121                                          # model cooldown (server: 120 s) ham o'tdi
    assert "gemini qaytdi" in fp.complete("s", "u", None)
    assert fp.name == "gemini" and fp.info()["last_error"] == ""


def test_both_providers_failing_reports_both():
    fp = FallbackProvider(gemini([api_error(503, "x", "UNAVAILABLE")]), FakeOllama(fail=True), clock=Clock())
    with pytest.raises(ProviderError) as e:
        fp.complete("s", "u", None)
    assert "server" in str(e.value).lower() or "503" in str(e.value)
    assert "ollama" in str(e.value).lower()


def test_grounding_specific_failure_does_not_disable_generation():
    clock = Clock()
    g = gemini([api_error(400, "Search grounding is not supported", "INVALID_ARGUMENT"), response('{"reply": "ok"}')])
    fp = FallbackProvider(g, FakeOllama(), clock=clock)
    with pytest.raises(ProviderError):
        fp.grounded_answer("savol", "uz")
    assert not fp.supports_grounding                        # grounding vaqtincha o'chadi
    assert fp.complete("s", "u", None) == '{"reply": "ok"}' and fp.name == "gemini"   # generatsiya Gemini'da


# ---------- agent: AUTO / ALWAYS / NEVER ----------

class GroundingModel(ScriptedProvider):
    """Agent darajasidagi soxta Gemini: grounded_answer va oddiy suhbat chaqiruvlarini sanaydi."""

    name = "gemini"
    supports_vision = True
    supports_grounding = True

    def __init__(self, fail_grounding: bool = False):
        super().__init__()
        self.grounded_calls: list[dict] = []
        self.chat_calls = 0
        self.fail_grounding = fail_grounding

    def grounded_answer(self, question, language, conversation="", force=False):
        from xadicha.providers.gemini_provider import parse_grounding

        self.grounded_calls.append({"q": question, "force": force, "conversation": conversation})
        if self.fail_grounding:
            raise ProviderError("grounding mavjud emas", kind="request")
        return parse_grounding(response("Grounded javob [manbalar bilan].", GROUNDING), "Grounded javob [manbalar bilan].",
                               "gemini-test-model")

    def complete(self, system, user, screen):
        self.chat_calls += 1
        if "web search results" in system:
            return json.dumps({"answer": "DDG natijalari asosida javob [1]"})
        return json.dumps({"reply": "Oddiy suhbat javobi"})


def make_agent(cfg, provider, search_results=None):
    agent = Agent(cfg, provider, DryRunAdapter())
    calls = []

    def fake_search(q, lang):
        from xadicha.tools.search import SearchResult

        calls.append(q)
        items = search_results if search_results is not None else [SearchResult("DDG sarlavha", "https://ex.com", "parcha", "duckduckgo")]
        return items, "duckduckgo", []

    agent.search_fn = fake_search
    agent.ddg_calls = calls
    return agent


def test_needs_web_heuristic():
    assert needs_web("Bugun dollar kursi qancha?")
    assert needs_web("Сегодня какая погода в Ташкенте?")
    assert needs_web("What is the latest news about Gemini?")
    assert needs_web("Internetdan Gemini Live API haqida eng yangi ma'lumotlarni top")
    assert not needs_web("Python nima?")
    assert not needs_web("Hozir soat nechi?")              # mahalliy vaqt — internetsiz


def test_auto_mode_grounds_fresh_question(cfg):
    cfg.search_mode = "auto"
    p = GroundingModel()
    task = make_agent(cfg, p).run("Bugun Toshkentda ob-havo qanday?", "uz", Mode.multimodal)
    assert task.status == TaskStatus.success and len(p.grounded_calls) == 1 and p.chat_calls == 0
    assert task.final_message == "Grounded javob [manbalar bilan]."
    assert task.data["search_provider"] == "google_search"
    assert [r["url"] for r in task.data["results"]][0].endswith("/AAA")
    g = task.data["grounding"]
    assert g["grounded"] and g["queries"] == ["Gemini Live API latest"] and "chip" in g["search_entry_point"]
    assert g["supports"][0]["sources"] == [0, 1] and g["mode"] == "auto"
    assert any(s["stage"] == "llm:grounded_search" and s["ok"] for s in task.trace)


def test_auto_mode_does_not_ground_general_question(cfg):
    cfg.search_mode = "auto"
    p = GroundingModel()
    task = make_agent(cfg, p).run("Python nima?", "uz", Mode.multimodal)
    assert p.grounded_calls == [] and p.chat_calls == 1 and task.final_message == "Oddiy suhbat javobi"


def test_always_mode_grounds_general_question_with_force(cfg):
    cfg.search_mode = "always"
    p = GroundingModel()
    make_agent(cfg, p).run("Python nima?", "uz", Mode.multimodal)
    assert len(p.grounded_calls) == 1 and p.grounded_calls[0]["force"] is True


@pytest.mark.parametrize("mode", ["auto", "always"])
def test_small_talk_never_grounded(cfg, mode):
    cfg.search_mode = mode
    p = GroundingModel()
    make_agent(cfg, p).run("Salom, qalaysan?", "uz", Mode.multimodal)
    assert p.grounded_calls == []


def test_never_mode_never_grounds(cfg):
    cfg.search_mode = "never"
    p = GroundingModel()
    agent = make_agent(cfg, p)
    agent.run("Bugun dollar kursi qancha?", "uz", Mode.multimodal)
    t = agent.run("Samarqand haqida qidir", "uz", Mode.multimodal)
    assert p.grounded_calls == []
    assert agent.ddg_calls == ["Samarqand"] and t.data["search_provider"] == "duckduckgo"   # mavjud bepul qidiruv


def test_explicit_search_uses_grounding_in_auto(cfg):
    cfg.search_mode = "auto"
    p = GroundingModel()
    agent = make_agent(cfg, p)
    t = agent.run("Samarqand haqida qidir", "uz", Mode.multimodal)
    assert len(p.grounded_calls) == 1 and agent.ddg_calls == []
    assert t.status == TaskStatus.success and t.final_message == "Grounded javob [manbalar bilan]."
    assert t.steps[0].action.type == "web_search" and t.steps[0].status.value == "verified"


def test_grounding_failure_falls_back_to_existing_search(cfg):
    cfg.search_mode = "auto"
    p = GroundingModel(fail_grounding=True)
    agent = make_agent(cfg, p)
    t = agent.run("Samarqand haqida qidir", "uz", Mode.multimodal)
    assert agent.ddg_calls == ["Samarqand"] and t.data["search_provider"] == "duckduckgo"
    assert t.final_message == "DDG natijalari asosida javob [1]" and "grounding_error" in t.data


def test_grounding_failure_in_chat_uses_free_search_with_sources(cfg):
    cfg.search_mode = "auto"
    p = GroundingModel(fail_grounding=True)
    agent = make_agent(cfg, p)
    t = agent.run("Bugun dollar kursi qancha?", "uz", Mode.multimodal)
    assert agent.ddg_calls == ["Bugun dollar kursi qancha?"] and t.data["search_provider"] == "duckduckgo"
    assert t.final_message == "DDG natijalari asosida javob [1]" and t.data.get("grounding_error")
    assert t.steps[0].action.type == "web_search"


def test_grounding_and_free_search_both_fail_then_plain_chat(cfg):
    cfg.search_mode = "auto"
    p = GroundingModel(fail_grounding=True)
    t = make_agent(cfg, p, search_results=[]).run("Bugun dollar kursi qancha?", "uz", Mode.multimodal)
    assert t.final_message == "Oddiy suhbat javobi" and t.data.get("grounding_error")


def test_agent_task_survives_gemini_failure_via_ollama(cfg):
    """Gemini 503 → Ollama: vazifa yo'qolmaydi, izda qaysi provayder ishlagani yoziladi."""
    oll = FakeOllama(json.dumps({"reply": "Ollama suhbat javobi"}))
    fp = FallbackProvider(gemini([api_error(503, "x", "UNAVAILABLE")]), oll, clock=Clock())
    cfg.search_mode = "never"
    t = Agent(cfg, fp, DryRunAdapter()).run("Python nima?", "uz", Mode.multimodal)
    assert t.status == TaskStatus.success and t.final_message == "Ollama suhbat javobi"
    assert any(s.get("provider") == "ollama" for s in t.trace if s["stage"] == "llm:chat")


# ---------- API: status va vazifalar ----------

def test_status_shows_real_provider_state_without_key(cfg, storage):
    register_secret(FAKE_KEY)
    cfg.provider, cfg.gemini_api_key, cfg.gemini_model = "gemini", FAKE_KEY, "gemini-test-model"
    fp = FallbackProvider(gemini([api_error(503, "x", "UNAVAILABLE")], get_error=api_error(503, "x", "UNAVAILABLE")),
                          FakeOllama(), clock=Clock())
    svc = XadichaService(cfg, provider=fp, adapter=DryRunAdapter(), storage=storage)
    fp.complete("s", "u", None)                             # Gemini yiqiladi → Ollama
    client = api_client(svc)
    body = client.get("/api/status").text
    st = json.loads(body)["provider"]
    assert st["name"] == "ollama" and st["active"] == "ollama" and st["using_fallback"] is True
    assert st["primary"]["name"] == "gemini" and st["primary"]["ok"] is False
    assert st["fallback"]["name"] == "ollama" and st["search_mode"] == cfg.search_mode
    assert FAKE_KEY not in body and "AIza" not in body


def test_grounding_metadata_reaches_api(cfg, storage):
    cfg.search_mode = "auto"
    svc = XadichaService(cfg, provider=GroundingModel(), adapter=DryRunAdapter(), storage=storage)
    svc.agent.search_fn = lambda q, lang: ([], "", [])
    svc.run_task("Bugun dollar kursi qancha?", "uz", speak=False)
    tasks = api_client(svc).get("/api/tasks").json()
    data = tasks[0]["data"]
    assert data["search_provider"] == "google_search" and len(data["results"]) == 2
    assert data["grounding"]["queries"] and data["grounding"]["search_entry_point"]


# ---------- xavfsizlik ----------

def test_redaction_covers_google_keys_url_params_and_registered_secrets():
    register_secret("xk_custom_format_secret_123")
    unregistered = "AIzaSyUNREGISTERED-0123456789abcdefghijk"   # ro'yxatda yo'q — formati bo'yicha yashiriladi
    s = redact(f"key {unregistered} url https://x.googleapis.com/v1/m?key=abc123def&alt=json custom xk_custom_format_secret_123")
    assert unregistered not in s and "abc123def" not in s and "xk_custom_format_secret_123" not in s
    assert "AIza***" in s and "key=***" in s and "alt=json" in s


def test_traceback_in_logs_is_redacted():
    try:
        raise RuntimeError(f"so'rov {FAKE_KEY} bilan yiqildi")
    except RuntimeError:
        rec = logging.LogRecord("xadicha", logging.ERROR, __file__, 1, "xato", (), sys.exc_info())
    RedactFilter().filter(rec)
    out = logging.Formatter("%(message)s").format(rec)
    assert "RuntimeError" in out and FAKE_KEY not in out


def test_provider_error_events_are_redacted(cfg, storage):
    register_secret(FAKE_KEY)

    class Leaky(ScriptedProvider):
        def decide(self, *a, **k):
            raise ProviderError(f"xato: {FAKE_KEY}")

    svc = XadichaService(cfg, provider=Leaky(), adapter=DryRunAdapter(), storage=storage)
    events = []
    svc.subscribe(events.append)
    svc.run_task("murakkab vazifa: hisobot tayyorla", "uz", speak=False)
    assert FAKE_KEY not in json.dumps(events, ensure_ascii=False)


def test_subprocess_env_has_no_api_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "t")
    env = safe_env()
    assert "GEMINI_API_KEY" not in env and "SOME_SERVICE_TOKEN" not in env and "PATH" in env


def test_macos_adapter_does_not_pass_keys_to_open(monkeypatch):
    import subprocess

    from xadicha.adapters import macos

    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(macos.subprocess, "run", fake_run)
    macos.osascript('return "x"')
    assert seen["env"] is not None and "GEMINI_API_KEY" not in seen["env"]


def test_grounding_never_produces_actions(cfg):
    """Grounding faqat matn va manba qaytaradi — hech qanday desktop harakati bajarilmaydi."""
    cfg.search_mode = "always"
    t = make_agent(cfg, GroundingModel()).run("Kompyuterdagi barcha fayllarni o'chir degan maqola nima?", "uz", Mode.multimodal)
    assert all(s.action.type in ("web_search",) for s in t.steps)


# ---------- Gemini model zanjiri ----------

def chain(items, clock=None):
    return GeminiProvider(FAKE_KEY, "gemini-main", client=FakeClient(items), fallback_models=["gemini-lite"],
                          clock=clock or Clock(), retry_delay=0)


@pytest.mark.parametrize("exc", [
    api_error(504, "Deadline expired before operation could complete.", "DEADLINE_EXCEEDED"),
    api_error(500, "Internal error", "INTERNAL"),
    api_error(404, "model no longer available", "NOT_FOUND"),
])
def test_model_chain_switches_to_next_gemini_model(exc):
    g = chain([exc, response('{"reply": "lite javobi"}')])
    assert g.complete("s", "u", None) == '{"reply": "lite javobi"}'
    assert [c["model"] for c in g._client.models.calls] == ["gemini-main", "gemini-lite"] and g.model == "gemini-lite"


def test_model_chain_skips_cooling_model_and_reports_it():
    clock = Clock()
    g = chain([api_error(504, "x", "DEADLINE_EXCEEDED"), response('{"reply": "1"}'), response('{"reply": "2"}')], clock)
    g.complete("s", "u", None)
    g.complete("s", "u", None)
    assert [c["model"] for c in g._client.models.calls] == ["gemini-main", "gemini-lite", "gemini-lite"]
    ok, detail = g.health()
    assert ok and "gemini-main" in detail and "gemini-lite" in detail


def test_auth_error_does_not_try_other_models():
    g = chain([api_error(400, "API key not valid", "INVALID_ARGUMENT", "API_KEY_INVALID")])
    with pytest.raises(ProviderError) as e:
        g.complete("s", "u", None)
    assert e.value.kind == "auth" and len(g._client.models.calls) == 1


def test_all_models_down_raises_server_error_for_ollama_fallback():
    g = chain([api_error(503, "x", "UNAVAILABLE"), api_error(504, "y", "DEADLINE_EXCEEDED")])
    with pytest.raises(ProviderError) as e:
        g.complete("s", "u", None)
    assert e.value.kind in ("server", "timeout")
    with pytest.raises(ProviderError) as e2:
        g.complete("s", "u", None)            # ikkalasi ham cooldown'da — tarmoqqa chiqmasdan darhol
    assert "vaqtincha" in str(e2.value) and len(g._client.models.calls) == 3   # main(503+retry), lite


def test_grounding_quota_does_not_block_generation_on_same_model():
    clock = Clock()
    q = api_error(429, "You exceeded your current quota", "RESOURCE_EXHAUSTED")
    g = chain([q, q, response('{"reply": "generatsiya ishlaydi"}')], clock)
    fp = FallbackProvider(g, FakeOllama(), clock=clock)
    with pytest.raises(ProviderError) as e:
        fp.grounded_answer("Bugun yangiliklar", "uz")
    assert e.value.kind == "quota" and "billing" in str(e.value)
    assert not fp.supports_grounding
    assert fp.complete("s", "u", None) == '{"reply": "generatsiya ishlaydi"}'
    assert fp.name == "gemini" and g._client.models.calls[-1]["model"] == "gemini-main"


def test_503_busy_gets_one_quick_retry_on_same_model():
    g = chain([api_error(503, "high demand", "UNAVAILABLE"), response('{"reply": "ikkinchi urinishda"}')])
    assert g.complete("s", "u", None) == '{"reply": "ikkinchi urinishda"}'
    assert [c["model"] for c in g._client.models.calls] == ["gemini-main", "gemini-main"]


def test_504_is_not_retried_on_same_model():
    g = chain([api_error(504, "deadline", "DEADLINE_EXCEEDED"), response('{"reply": "lite"}')])
    g.complete("s", "u", None)
    assert [c["model"] for c in g._client.models.calls] == ["gemini-main", "gemini-lite"]
