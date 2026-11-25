"""Suhbat rejimi: oddiy gaplar faqat javob oladi, hech qanday amal bajarilmaydi (simulyatsiya — soxta model)."""

from __future__ import annotations

import json

import pytest

from conftest import ScriptedProvider, api_client
from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent, chat_fallback, clean_spoken
from xadicha.models import Mode, TaskStatus
from xadicha.providers.rule_based import RuleBasedProvider
from xadicha.router import detect_chat, route
from xadicha.service import XadichaService
from xadicha.understand import understand

CHAT = ["Salom, qalaysan?", "Assalomu alaykum", "Rahmat", "Rahmat, zo'r ishlading", "Sen kimsan?",
        "Nima qila olasan?", "Bugun kayfiyatim yaxshi", "Hozir soat nechi?", "Samarqand qayerda?", "Python nima?",
        "Салом, қалайсиз?", "Раҳмат", "Привет, как дела?", "Спасибо!", "Кто ты?", "Мне грустно",
        "Hello", "How are you?", "Who are you?", "What can you do?", "Thanks a lot", "ok"]

# Amal so'ralgan — salom yoki savol bo'lsa ham buyruq yo'lida qolishi SHART
COMMANDS = ["Safari ni och", "Rahmat, Safari ni och", "Salom, ovozni oshir", "Samarqand haqida qidir",
            "Привет, открой Safari", "Hello, open Calculator", "Message Ali on Telegram saying hello",
            "Telegramga xabar yoz", "Which app is open right now?", "Ekranda nima bor?", "Что сейчас на экране?",
            "Describe what is on my screen", "hisobot faylini top", "Notes ni och va yoz", "Make it quieter",
            "Сделай потише", "Set the volume to 60", "Go to github.com", "Telegram nima?", "kun.uz saytiga kir"]


@pytest.mark.parametrize("text", CHAT)
def test_chat_detected(text):
    assert detect_chat(text), text
    assert route(text, "uz").path == "chat"


@pytest.mark.parametrize("text", COMMANDS)
def test_commands_never_become_chat(text):
    assert not detect_chat(text), text
    assert route(text, "uz").path != "chat"


class ChatModel(ScriptedProvider):
    name = "chatmodel"
    supports_vision = True

    def __init__(self, reply: str | None = "Yaxshi, rahmat! Sizga qanday yordam bera olaman?", fail: bool = False):
        super().__init__()
        self.reply, self.raise_, self.calls = reply, fail, []

    def complete(self, system, user, screen):
        self.calls.append({"system": system, "user": user, "screen": screen})
        if self.raise_:
            raise RuntimeError("model yiqildi")
        return json.dumps({"reply": self.reply}, ensure_ascii=False)


class Spy(DryRunAdapter):
    def __init__(self):
        super().__init__()
        self.executed = []

    def execute(self, action):
        self.executed.append(action)
        return super().execute(action)


def test_chat_replies_without_actions_or_screenshot(cfg):
    shots = []
    model, spy = ChatModel(), Spy()
    agent = Agent(cfg, model, spy, screen_fn=lambda: shots.append(1))
    task = agent.run("Salom, qalaysan?", "uz", Mode.multimodal)
    assert task.status == TaskStatus.success and task.planner == "chat" and task.intent == "chat"
    assert task.final_message == "Yaxshi, rahmat! Sizga qanday yordam bera olaman?"
    assert task.steps == [] and spy.executed == [] and shots == []      # hech narsa bajarilmadi, ekran olinmadi
    assert task.llm_calls == 1 and len(model.calls) == 1 and model.calls[0]["screen"] is None
    assert "CONVERSATION mode" in model.calls[0]["system"] and "Uzbek" in model.calls[0]["system"]
    assert any(s["stage"] == "llm:chat" for s in task.trace)


def test_chat_uses_language_and_conversation(cfg):
    from xadicha.conversation import Conversation

    model = ChatModel("Привет! Чем помочь?")
    agent = Agent(cfg, model, DryRunAdapter())
    agent.conversation = Conversation()
    agent.conversation.add_user("Safari ni och", "uz")
    task = agent.run("Привет, как дела?", "ru", Mode.multimodal)
    assert "Russian" in model.calls[0]["system"] and "Safari ni och" in model.calls[0]["system"]
    assert task.final_message == "Привет! Чем помочь?"


def test_chat_falls_back_when_model_fails_or_missing(cfg):
    t1 = Agent(cfg, ChatModel(fail=True), DryRunAdapter()).run("Rahmat", "uz", Mode.multimodal)
    assert t1.status == TaskStatus.success and t1.final_message == chat_fallback("Rahmat", "uz")
    t2 = Agent(cfg, ChatModel(reply=""), DryRunAdapter()).run("Hello", "en", Mode.multimodal)
    assert t2.final_message.startswith("Hi! I'm XADICHA")
    t3 = Agent(cfg, RuleBasedProvider(), DryRunAdapter()).run("Sen kimsan?", "uz", Mode.multimodal)
    assert t3.final_message.startswith("Men XADICHA") and t3.llm_calls == 0


def test_chat_fallback_kinds():
    assert chat_fallback("Спасибо", "ru").startswith("Не за что")
    assert chat_fallback("Salom", "uz").startswith("Salom!")
    assert chat_fallback("Who are you?", "en").startswith("I'm XADICHA")
    assert "model" in chat_fallback("Samarqand qayerda?", "uz")      # model yo'q — javob to'qilmaydi


def test_clean_spoken():
    assert clean_spoken("**Salom!** Bu `kod` [1]") == "Salom! Bu kod"
    long = "Bu gap. " * 200
    out = clean_spoken(long, limit=100)
    assert len(out) <= 100 and out.endswith(".")


def test_voice_chat_needs_no_clarification():
    for llm in (True, False):
        a = understand("Salom, qalaysan?", "uz", 0.9, llm_available=llm)
        assert a.intent == "chat" and not a.needs_clarification
    assert understand("Salom", "uz", 0.2).needs_clarification     # ASR ishonchi past — so'raladi


def test_chat_through_service_api(cfg):
    model = ChatModel("Salom! Yordam beraymi?")
    svc = XadichaService(cfg, provider=model, adapter=DryRunAdapter())
    c = api_client(svc)
    r = c.post("/api/tasks", json={"instruction": "Salom", "language": "uz", "mode": "C"})
    assert r.status_code == 202
    import time

    for _ in range(50):
        tasks = c.get("/api/tasks").json()
        if tasks and tasks[0]["status"] != "running":
            break
        time.sleep(0.05)
    t = tasks[0]
    assert t["planner"] == "chat" and t["final_message"] == "Salom! Yordam beraymi?" and t["steps"] == []
    turns = c.get("/api/conversation").json()["turns"]
    assert [x["role"] for x in turns][-2:] == ["user", "assistant"]
