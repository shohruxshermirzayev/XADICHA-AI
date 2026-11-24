from conftest import ScriptedProvider

from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent
from xadicha.models import Mode, StepStatus, TaskStatus


def make(cfg, storage, provider, adapter=None, confirm=None):
    events = []
    agent = Agent(cfg, provider, adapter or DryRunAdapter(), storage,
                  confirm=confirm, on_event=events.append, screen_fn=None)
    return agent, events


def test_mode_c_success_with_verification(cfg, storage):
    p = ScriptedProvider([
        {"intent": "open_app", "action": {"type": "open_app", "app": "Notes"}, "expected_outcome": "Notes is open"},
        {"previous_step_ok": True, "action": {"type": "type_text", "text": "salom"}, "expected_outcome": "text typed"},
        {"previous_step_ok": True, "done": True, "success": True, "final_message": "Bajarildi"},
    ])
    agent, events = make(cfg, storage, p)
    t = agent.run("Notes ni och va salom yoz", "uz", Mode.multimodal)
    assert t.status == TaskStatus.success
    assert [s.status for s in t.steps] == [StepStatus.verified, StepStatus.verified]
    assert t.intent == "open_app" and t.llm_calls == 3
    assert storage.get_task(t.id).status == TaskStatus.success
    kinds = [e["type"] for e in events]
    assert kinds[0] == "task_started" and kinds[-1] == "task_finished" and "step_verified" in kinds


def test_mode_c_visual_failure_then_recovery(cfg, storage):
    p = ScriptedProvider([
        {"action": {"type": "click", "x": 1, "y": 1}, "expected_outcome": "menu opens"},
        {"previous_step_ok": False, "action": {"type": "hotkey", "keys": ["command", "l"]}},
        {"previous_step_ok": True, "done": True, "success": True, "final_message": "ok"},
    ])
    agent, _ = make(cfg, storage, p)
    t = agent.run("x", "uz")
    assert t.status == TaskStatus.success
    assert t.steps[0].status == StepStatus.failed and t.steps[0].verified is False
    assert t.recoveries == 1


def test_mode_c_too_many_failures(cfg, storage):
    p = ScriptedProvider([{"action": {"type": "open_app", "app": "X"}}] * 6)
    agent, _ = make(cfg, storage, p, adapter=DryRunAdapter(fail_types={"open_app"}))
    t = agent.run("X ni och", "uz")
    assert t.status == TaskStatus.failed
    assert len(t.steps) == cfg.max_retries + 1


def test_high_risk_denied_stops_task(cfg, storage, tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("x")
    p = ScriptedProvider([{"action": {"type": "delete_path", "path": str(target)}, "risk": "low"}])
    adapter = DryRunAdapter()
    asked = []
    agent, _ = make(cfg, storage, p, adapter=adapter, confirm=lambda *a: asked.append(a) or False)
    t = agent.run("faylni o'chir", "uz")
    assert asked, "o'chirishdan oldin tasdiq so'ralishi shart"
    assert t.status == TaskStatus.cancelled
    assert t.steps[0].status == StepStatus.denied
    assert adapter.executed == [], "rad etilgan harakat bajarilmasligi kerak"


def test_high_risk_approved_executes(cfg, storage, tmp_path):
    p = ScriptedProvider([
        {"action": {"type": "delete_path", "path": str(tmp_path / "a")}},
        {"previous_step_ok": True, "done": True, "success": True},
    ])
    adapter = DryRunAdapter()
    agent, _ = make(cfg, storage, p, adapter=adapter, confirm=lambda *a: True)
    t = agent.run("o'chir", "uz")
    assert t.status == TaskStatus.success and len(adapter.executed) == 1


def test_blocked_even_if_approved(cfg, storage):
    p = ScriptedProvider([{"action": {"type": "delete_path", "path": "/System"}}])
    adapter = DryRunAdapter()
    agent, _ = make(cfg, storage, p, adapter=adapter, confirm=lambda *a: True)
    t = agent.run("tizimni o'chir", "uz")
    assert t.status == TaskStatus.cancelled and adapter.executed == []


def test_provider_unavailable(cfg, storage):
    agent, events = make(cfg, storage, ScriptedProvider(fail=True))
    t = agent.run("Safari ni och", "uz")
    assert t.status == TaskStatus.failed
    assert "AI modeliga" in t.final_message
    assert any(e["type"] == "error" for e in events)


def test_stop_cancels(cfg, storage):
    p = ScriptedProvider([{"action": {"type": "wait", "seconds": 0}}] * 5)
    agent, _ = make(cfg, storage, p)
    original = agent._execute

    def execute_then_stop(*a, **kw):
        r = original(*a, **kw)
        agent.stop()
        return r

    agent._execute = execute_then_stop
    t = agent.run("kut", "uz")
    assert t.status == TaskStatus.cancelled and len(t.steps) == 1


def test_max_steps(cfg, storage):
    p = ScriptedProvider([{"previous_step_ok": True, "action": {"type": "scroll", "amount": -1}}] * 20)
    agent, _ = make(cfg, storage, p)
    t = agent.run("aylantir", "en")
    assert t.status == TaskStatus.failed and len(t.steps) == cfg.max_steps
    assert "step limit" in t.final_message


def test_mode_a_rule_based(cfg, storage):
    adapter = DryRunAdapter()
    agent, _ = make(cfg, storage, ScriptedProvider(), adapter=adapter)
    t = agent.run("Открой Telegram", "ru", Mode.voice_only)
    assert t.status == TaskStatus.success and adapter.executed[0].app == "Telegram"
    assert t.llm_calls == 0


def test_mode_a_unknown(cfg, storage):
    agent, _ = make(cfg, storage, ScriptedProvider())
    t = agent.run("nimadir tushunarsiz", "uz", Mode.voice_only)
    assert t.status == TaskStatus.failed and not t.steps


def test_mode_b_plan(cfg, storage):
    p = ScriptedProvider(plan={"intent": "x", "final_message": "tayyor", "steps": [
        {"action": {"type": "open_app", "app": "Safari"}},
        {"action": {"type": "open_url", "url": "https://kun.uz"}},
    ]})
    adapter = DryRunAdapter()
    agent, _ = make(cfg, storage, p, adapter=adapter)
    t = agent.run("kun.uz ni Safari da och", "uz", Mode.llm_plan)
    assert t.status == TaskStatus.success and len(adapter.executed) == 2 and t.llm_calls == 1


def test_mode_b_stops_on_failure(cfg, storage):
    p = ScriptedProvider(plan={"steps": [{"action": {"type": "open_app", "app": "A"}},
                                         {"action": {"type": "open_url", "url": "https://a.uz"}}]})
    adapter = DryRunAdapter(fail_types={"open_app"})
    agent, _ = make(cfg, storage, p, adapter=adapter)
    t = agent.run("x", "uz", Mode.llm_plan)
    assert t.status == TaskStatus.failed and len(adapter.executed) == 1


# --- tezkor yo'l (fast path) ---

def test_fast_path_simple_command_skips_model(cfg, storage):
    cfg.fast_path = True
    p = ScriptedProvider([{"done": True, "final_message": "model chaqirilmasligi kerak"}])
    adapter = DryRunAdapter()
    agent, _ = make(cfg, storage, p, adapter=adapter)
    t = agent.run("Safari ni och", "uz")
    assert t.status == TaskStatus.success and t.planner == "rules" and t.llm_calls == 0
    assert adapter.executed[0].app == "Safari" and p.calls == []


def test_fast_path_not_used_for_multi_step(cfg, storage):
    cfg.fast_path = True
    p = ScriptedProvider([{"action": {"type": "open_app", "app": "Notes"}},
                          {"previous_step_ok": True, "done": True, "success": True}])
    agent, _ = make(cfg, storage, p)
    t = agent.run('Notes ni och va "Salom dunyo" deb yoz', "uz")
    assert t.planner == "llm" and t.llm_calls == 2


def test_fast_path_failure_falls_back_to_model(cfg, storage):
    cfg.fast_path = True
    p = ScriptedProvider([{"previous_step_ok": False, "done": True, "success": False, "final_message": "topilmadi"}])
    agent, _ = make(cfg, storage, p, adapter=DryRunAdapter(fail_types={"open_app"}))
    t = agent.run("Brauzer ni och", "uz")
    assert t.planner == "llm" and t.llm_calls == 1 and p.calls[0]["history"], "model xato qadamni ko'rishi kerak"


def test_fast_path_disabled_for_experiments(cfg, storage):
    cfg.fast_path = False
    p = ScriptedProvider([{"action": {"type": "open_app", "app": "Safari"}},
                          {"previous_step_ok": True, "done": True, "success": True}])
    agent, _ = make(cfg, storage, p)
    t = agent.run("Safari ni och", "uz")
    assert t.planner == "llm" and t.llm_calls == 2
