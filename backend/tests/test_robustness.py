"""Kichik modelning noto'g'ri javoblari va kutilmagan xatolarga chidamlilik."""

import pytest
from conftest import ScriptedProvider

from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent
from xadicha.models import TaskRecord, TaskStatus
from xadicha.providers.base import LLMProvider, ProviderError, normalize_decision, parse_decision


class RawProvider(LLMProvider):
    name = "raw"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user, screen):
        self.prompts.append(user)
        return self.replies.pop(0)


def test_normalize_fixes_common_small_model_mistakes():
    d = normalize_decision({"risk": "none", "action": {"type": "Open", "app": "Safari"}, "thought": None})
    assert d["risk"] == "medium" and d["action"]["type"] == "open_app" and d["thought"] == ""
    d = normalize_decision({"action": {"type": "press", "keys": "command+l"}})
    assert d["action"] == {"type": "hotkey", "keys": ["command", "l"]}
    assert normalize_decision({"action": "click the button"})["action"] is None


def test_parse_decision_from_messy_text():
    d = parse_decision('Mana: ```json\n{"action": {"type": "navigate", "url": "https://youtube.com"}, "risk": "LOW"}\n```')
    assert d.action.type == "open_url" and d.risk.value == "low"


def test_invalid_reply_is_retried_with_feedback():
    p = RawProvider(['{"action": {"type": "teleport"}}', '{"done": true, "final_message": "ok"}'])
    d = p.decide("x", [], None, "uz")
    assert d.done and len(p.prompts) == 2 and "invalid" in p.prompts[1]


def test_two_invalid_replies_raise_provider_error():
    p = RawProvider(["salom", "yana salom"])
    with pytest.raises(ProviderError):
        p.decide("x", [], None, "uz")


def test_unexpected_exception_never_leaves_task_running(cfg, storage):
    class Boom(ScriptedProvider):
        def decide(self, *a, **kw):
            raise KeyError("kutilmagan")

    events = []
    agent = Agent(cfg, Boom(), DryRunAdapter(), storage, on_event=events.append)
    t = agent.run("YouTube'da qo'shiq qo'y", "uz")
    assert t.status == TaskStatus.failed and t.finished_at
    assert storage.get_task(t.id).status == TaskStatus.failed
    assert events[-1]["type"] == "task_finished"


def test_stale_running_tasks_are_closed_on_startup(storage):
    t = TaskRecord(instruction="yarim qolgan")
    storage.save_task(t)
    assert storage.fail_stale_running() == 1
    assert storage.get_task(t.id).status == TaskStatus.failed


def test_prompts_format_without_errors():
    # Ko'rsatmadagi { } belgilari .format() ni buzmasligi kerak (shunday xato real Mac'da topilgan)
    from xadicha.providers.base import LLMProvider
    from xadicha.vision.screen import Screenshot

    class P(LLMProvider):
        def complete(self, s, u, sc):
            return "{}"

    text = P().system_prompt("uz", Screenshot("", 1024, 640, 1.4))
    assert "1024x640" in text and '{"seconds": 2}' in text
