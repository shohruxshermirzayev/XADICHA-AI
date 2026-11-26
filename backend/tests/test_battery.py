"""Batareya zaryadi: tushunish (modelsiz), macOS `pmset -g batt` tahlili, Windows psutil, javob matni, xavfsizlik.

Haqiqiy buyruq chaqirilmaydi — subprocess va psutil mock qilinadi (simulyatsiya).
"""

from __future__ import annotations

import subprocess
import sys
import types
from collections import namedtuple

import pytest

from xadicha.adapters.base import DryRunAdapter, ExecResult
from xadicha.agent import Agent
from xadicha.models import Action, Mode, RiskLevel, TaskStatus, tool_spec
from xadicha.providers.rule_based import battery_reply, parse_command
from xadicha.router import route
from xadicha import safety

BATTERY_PHRASES = [
    # o'zbek (lotin)
    "zaryad qancha", "zaryadim qancha qoldi", "batareya necha foiz", "quvvat qancha", "zaryad nechchi",
    "Zaryadlovchini ulash kerakmi?",
    # o'zbek (kirill)
    "заряд қанча", "батарея неча фоиз", "қувват қанча",
    # rus
    "сколько заряда", "какой заряд", "уровень батареи", "сколько процентов батареи",
    # ingliz
    "battery level", "how much battery", "what's my battery", "battery percentage",
]


@pytest.mark.parametrize("text", BATTERY_PHRASES)
def test_battery_phrases_become_battery_action(text):
    intent, actions, _ = parse_command(text, "uz")
    assert intent == "system" and actions == [Action(type="system", control="battery")], text
    r = route(text, "uz")
    assert r.path == "fast" and r.actions[0].control == "battery", text   # LLM'siz, darhol


@pytest.mark.parametrize("text,control", [
    ("ovozni ko'tar", "volume_up"), ("ovozni 40 ga qo'y", "volume_set"), ("Ovoz balandligini kamaytir", "volume_down"),
    ("ovozni o'chir", "mute"), ("yorug'likni oshir", "brightness_up"), ("сделай тише", "volume_down"),
    ("brightness down", "brightness_down"), ("Screenshot ol", "screenshot"),
])
def test_existing_system_commands_unchanged(text, control):
    _, actions, _ = parse_command(text, "uz")
    assert actions and actions[0].control == control


def test_power_off_request_is_not_a_battery_query():
    assert route("kompyuter quvvatini o'chir", "uz").actions == []


# ---------- macOS: pmset -g batt ----------

PMSET = {
    "charging": "Now drawing from 'AC Power'\n -InternalBattery-0 (id=6488163)\t76%; charging; 0:45 remaining present: true\n",
    "discharging": "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=6488163)\t23%; discharging; 1:40 remaining present: true\n",
    "charged": "Now drawing from 'AC Power'\n -InternalBattery-0 (id=6488163)\t100%; charged; 0:00 remaining present: true\n",
    "ac_not_charging": "Now drawing from 'AC Power'\n -InternalBattery-0 (id=6488163)\t80%; AC attached; not charging present: true\n",
    "no_estimate": "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=6488163)\t15%; discharging; (no estimate) present: true\n",
    "no_battery": "Now drawing from 'AC Power'\n",
}


@pytest.mark.parametrize("key,expect", [
    ("charging", {"present": True, "percent": 76, "state": "charging", "minutes_left": 45, "source": "ac"}),
    ("discharging", {"present": True, "percent": 23, "state": "discharging", "minutes_left": 100, "source": "battery"}),
    ("charged", {"present": True, "percent": 100, "state": "charged", "minutes_left": None, "source": "ac"}),
    ("ac_not_charging", {"present": True, "percent": 80, "state": "ac", "minutes_left": None, "source": "ac"}),
    ("no_estimate", {"present": True, "percent": 15, "state": "discharging", "minutes_left": None, "source": "battery"}),
    ("no_battery", {"present": False, "source": "ac"}),
])
def test_parse_pmset(key, expect):
    from xadicha.adapters.macos import parse_pmset

    assert parse_pmset(PMSET[key]) == expect


def test_macos_adapter_runs_only_exact_pmset(monkeypatch):
    from xadicha.adapters import macos

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, PMSET["discharging"], "")

    monkeypatch.setattr(macos.subprocess, "run", fake_run)
    r = macos.MacOSAdapter()._do_system(Action(type="system", control="battery"))
    assert seen["cmd"] == ["pmset", "-g", "batt"] and not seen["kw"].get("shell") and seen["kw"]["timeout"] > 0
    assert r.ok and r.data["percent"] == 23 and "23%" in r.detail


def test_macos_adapter_without_battery_does_not_fail(monkeypatch):
    from xadicha.adapters import macos

    monkeypatch.setattr(macos.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, PMSET["no_battery"], ""))
    r = macos.MacOSAdapter()._do_system(Action(type="system", control="battery"))
    assert r.ok and r.data == {"present": False, "source": "ac"} and "topilmadi" in r.detail


# ---------- Windows: psutil ----------

Batt = namedtuple("sbattery", "percent secsleft power_plugged")


def fake_psutil(value):
    mod = types.SimpleNamespace(POWER_TIME_UNLIMITED=-2, POWER_TIME_UNKNOWN=-1, sensors_battery=lambda: value)
    return mod


@pytest.mark.parametrize("value,expect", [
    (Batt(76.0, -2, True), {"present": True, "percent": 76, "state": "charging", "minutes_left": None, "source": "ac"}),
    (Batt(23.0, 6000, False), {"present": True, "percent": 23, "state": "discharging", "minutes_left": 100, "source": "battery"}),
    (Batt(100.0, -2, True), {"present": True, "percent": 100, "state": "charged", "minutes_left": None, "source": "ac"}),
    (Batt(40.0, -1, False), {"present": True, "percent": 40, "state": "discharging", "minutes_left": None, "source": "battery"}),
    (None, {"present": False, "source": ""}),
])
def test_windows_battery_via_psutil(monkeypatch, value, expect):
    from xadicha.adapters.windows import WindowsAdapter

    monkeypatch.setitem(sys.modules, "psutil", fake_psutil(value))
    r = WindowsAdapter.__new__(WindowsAdapter)._battery()
    assert r.ok and r.data == expect


# ---------- DryRun, javob matni, xavfsizlik ----------

def test_dry_run_accepts_battery_without_inventing_numbers():
    r = DryRunAdapter().execute(Action(type="system", control="battery"))
    assert r.ok and r.data == {"simulated": True}
    assert "simulyatsiya" in battery_reply(r.data, "uz")


@pytest.mark.parametrize("info,lang,text", [
    ({"present": True, "percent": 76, "state": "charging", "minutes_left": 45}, "uz", "Zaryad 76%, quvvatlanmoqda."),
    ({"present": True, "percent": 23, "state": "discharging", "minutes_left": 100}, "uz",
     "Zaryad 23%, taxminan 1 soat 40 daqiqaga yetadi."),
    ({"present": True, "percent": 100, "state": "charged", "minutes_left": None}, "uz", "Zaryad 100%, to'liq."),
    ({"present": True, "percent": 76, "state": "charging", "minutes_left": None}, "ru", "Заряд 76%, идёт зарядка."),
    ({"present": True, "percent": 76, "state": "charging", "minutes_left": None}, "en", "Battery is at 76%, charging."),
    ({"present": True, "percent": 15, "state": "discharging", "minutes_left": 40}, "uz",
     "Zaryad 15%, taxminan 40 daqiqaga yetadi. Zaryadlovchini ulashni maslahat beraman."),
    ({"present": True, "percent": 12, "state": "discharging", "minutes_left": None}, "ru",
     "Заряд 12%. Советую подключить зарядку."),
    ({"present": True, "percent": 10, "state": "discharging", "minutes_left": None}, "en",
     "Battery is at 10%. I recommend plugging in the charger."),
    ({"present": True, "percent": 15, "state": "charging", "minutes_left": None}, "uz", "Zaryad 15%, quvvatlanmoqda."),
    ({"present": False}, "uz", "Batareya topilmadi."),
])
def test_battery_reply(info, lang, text):
    assert battery_reply(info, lang) == text


def test_battery_is_read_only_and_never_needs_confirmation():
    a = Action(type="system", control="battery")
    assert tool_spec(a).read_only is True and safety.is_read_only_control(a)
    assert safety.final_risk(a, RiskLevel.high) == RiskLevel.low
    assert not safety.is_read_only_control(Action(type="system", control="volume_up"))
    assert tool_spec(Action(type="system", control="volume_up")).read_only is False


class BatteryAdapter(DryRunAdapter):
    def execute(self, action):
        self.executed.append(action)
        return ExecResult(True, "batareya: 23%, discharging", verified=True,
                          data={"present": True, "percent": 23, "state": "discharging", "minutes_left": 100, "source": "battery"})


def test_agent_speaks_real_battery_value_without_confirmation(cfg):
    from conftest import ScriptedProvider

    cfg.fast_path, cfg.confirm_risk = True, "low"            # eng qattiq tasdiq rejimida ham so'ralmaydi
    asked = []
    adapter = BatteryAdapter()
    agent = Agent(cfg, ScriptedProvider(), adapter, confirm=lambda *a: asked.append(a) or False)
    task = agent.run("zaryad qancha", "uz", Mode.multimodal)
    assert task.status == TaskStatus.success and asked == []
    assert task.final_message == "Zaryad 23%, taxminan 1 soat 40 daqiqaga yetadi."
    assert adapter.executed[0].control == "battery"
    ru = Agent(cfg, ScriptedProvider(), BatteryAdapter()).run("сколько заряда", "ru", Mode.multimodal)
    assert ru.final_message == "Заряд 23%, хватит примерно на 1 ч 40 мин."
