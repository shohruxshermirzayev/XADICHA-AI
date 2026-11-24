from pathlib import Path

from xadicha import safety
from xadicha.models import Action, RiskLevel


def test_delete_is_always_high():
    assert safety.classify(Action(type="delete_path", path="~/x")) == RiskLevel.high


def test_model_cannot_lower_risk():
    a = Action(type="delete_path", path="~/x")
    assert safety.final_risk(a, RiskLevel.low) == RiskLevel.high


def test_model_can_raise_risk():
    a = Action(type="open_app", app="Notes")
    assert safety.final_risk(a, RiskLevel.high) == RiskLevel.high


def test_sensitive_text_is_high():
    for text in ["pip install requests", "Отправить сообщение", "to'lovni tasdiqla"]:
        assert safety.classify(Action(type="type_text", text=text)) == RiskLevel.high


def test_click_on_send_context_is_high():
    a = Action(type="click", x=10, y=10)
    assert safety.final_risk(a, RiskLevel.medium, context="message is sent to Ali") == RiskLevel.high


def test_terminal_is_high():
    assert safety.classify(Action(type="open_app", app="Terminal")) == RiskLevel.high
    assert safety.classify(Action(type="open_app", app="Safari")) == RiskLevel.low


def test_file_outside_workspace_is_high(tmp_path: Path):
    inside = Action(type="create_folder", path=str(tmp_path / "a"))
    outside = Action(type="create_folder", path="/tmp/elsewhere-xyz")
    assert safety.classify(inside, tmp_path) == RiskLevel.medium
    assert safety.classify(outside, tmp_path / "sub") == RiskLevel.high


def test_confirmation_threshold():
    assert safety.needs_confirmation(RiskLevel.high, "high")
    assert not safety.needs_confirmation(RiskLevel.medium, "high")
    assert safety.needs_confirmation(RiskLevel.medium, "medium")
    assert safety.needs_confirmation(RiskLevel.low, "low")


def test_system_paths_blocked(tmp_path: Path):
    assert safety.blocked_reason(Action(type="delete_path", path="/System/Library"), tmp_path)
    assert safety.blocked_reason(Action(type="delete_path", path=str(tmp_path)), tmp_path)
    assert safety.blocked_reason(Action(type="create_folder", path=str(tmp_path / "ok")), tmp_path) is None
