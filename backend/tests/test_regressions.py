"""Muhandislik tekshiruvida topilgan xatolar uchun regressiya testlari.

Har bir test aniq bir xatoni qayd etadi: tuzatishdan oldin u yiqilgan (yoki xatti-harakat noto'g'ri bo'lgan).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import ScriptedProvider
from fastapi.testclient import TestClient

from xadicha import safety
from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent
from xadicha.api import create_app
from xadicha.models import Action, RiskLevel, StepStatus, TaskStatus
from xadicha.providers.rule_based import parse_command
from xadicha.service import XadichaService, mic_error_message
from xadicha.speech.stt import Transcript, rms_level


# ---------------------------------------------------------------- xavfsizlik: aylanib o'tishlar

def test_dotdot_traversal_into_system_dir_is_blocked(tmp_path: Path):
    # Avval: "/tmp/../etc/hosts" — regex yechilmagan yo'lga qo'llanib, taqiqdan o'tib ketardi
    a = Action(type="delete_path", path="/tmp/../etc/hosts")
    assert safety.blocked_reason(a, tmp_path)


def test_symlink_into_system_dir_is_blocked(tmp_path: Path):
    link = tmp_path.parent / f"link-{tmp_path.name}"
    link.symlink_to("/etc")
    try:
        a = Action(type="create_file", path=str(link / "evil.conf"))
        assert safety.blocked_reason(a, tmp_path)
    finally:
        link.unlink()


def test_program_files_x86_is_blocked(tmp_path: Path):
    a = Action(type="create_file", path="C:\\Program Files (x86)\\x.txt")
    assert safety.blocked_reason(a, tmp_path)
    assert safety.blocked_reason(Action(type="delete_path", path="C:\\Windows\\System32"), tmp_path)


def test_sensitive_home_dirs_blocked_even_inside_workspace():
    home = Path.home()
    for rel in (".ssh/authorized_keys", "Library/LaunchAgents/x.plist", ".zshrc", ".aws/credentials"):
        a = Action(type="create_file", path=str(home / rel))
        assert safety.blocked_reason(a, home), rel


def test_home_root_folders_cannot_be_deleted_but_contents_can_be_asked():
    home = Path.home()
    assert safety.blocked_reason(Action(type="delete_path", path="~/Documents"), home)
    assert safety.blocked_reason(Action(type="delete_path", path="~"), home)
    # ichidagi fayl — taqiqlanmaydi, lekin yuqori xavf (tasdiq so'raladi)
    inner = Action(type="delete_path", path="~/Documents/eski.txt")
    assert safety.blocked_reason(inner, home) is None
    assert safety.classify(inner, home) == RiskLevel.high


def test_open_url_with_local_path_or_scheme_is_blocked(tmp_path: Path):
    # Avval: low xavf — `open /System/.../Terminal.app` Terminal'ni tasdiqsiz ochardi
    for url in ("/System/Applications/Utilities/Terminal.app", "file:///etc/passwd", "smb://x/y",
                "javascript:alert(1)", "-a Terminal", "x-apple.systempreferences:"):
        a = Action(type="open_url", url=url)
        assert safety.blocked_reason(a, tmp_path), url
        assert safety.classify(a) == RiskLevel.high
    ok = Action(type="open_url", url="https://kun.uz")
    assert safety.blocked_reason(ok, tmp_path) is None and safety.classify(ok) == RiskLevel.low
    assert safety.classify(Action(type="open_url", url="mailto:a@b.uz")) == RiskLevel.medium


def test_app_name_with_shell_metacharacters_is_blocked(tmp_path: Path):
    # Avval: Windows'da `cmd /c start "" calc&whoami` ikkinchi buyruqni ham bajarardi
    for app in ("calc&whoami", "notepad|x", "a>b", "%COMSPEC%", "-a Terminal"):
        assert safety.blocked_reason(Action(type="open_app", app=app), tmp_path), app
    assert safety.blocked_reason(Action(type="open_app", app="Google Chrome"), tmp_path) is None


def test_relative_path_is_resolved_against_workspace(cfg, storage):
    # Avval: nisbiy yo'l jarayonning joriy papkasiga (backend/) nisbatan yaratilardi
    adapter = DryRunAdapter()
    p = ScriptedProvider([{"action": {"type": "create_folder", "path": "Hisobot"}},
                          {"previous_step_ok": True, "done": True, "success": True}])
    Agent(cfg, p, adapter, storage).run("papka yarat")
    assert adapter.executed[0].path == str(cfg.workspace / "Hisobot")


# ---------------------------------------------------------------- agent: rad etilgan harakat bajarilmaydi

def _delete_task(tmp_path):
    return ScriptedProvider([{"action": {"type": "delete_path", "path": str(tmp_path / "x")}},
                             {"previous_step_ok": True, "done": True, "success": True}])


@pytest.mark.parametrize("answer,status,detail_part", [
    (False, TaskStatus.cancelled, "rad"),
    ("denied", TaskStatus.cancelled, "rad"),
    ("timeout", TaskStatus.cancelled, "muddati"),
    ("cancelled", TaskStatus.cancelled, "to'xtatildi"),
    (None, TaskStatus.cancelled, "rad"),
    ("yes", TaskStatus.cancelled, "rad"),      # truthy satr ruxsat EMAS — faqat aniq True
])
def test_any_non_true_confirmation_never_executes(cfg, storage, tmp_path, answer, status, detail_part):
    adapter = DryRunAdapter()
    t = Agent(cfg, _delete_task(tmp_path), adapter, storage, confirm=lambda *a: answer).run("o'chir")
    assert adapter.executed == []
    assert t.status == status and detail_part in t.steps[0].detail
    assert t.steps[0].status == StepStatus.denied


def test_timeout_message_differs_from_rejection(cfg, storage, tmp_path):
    t = Agent(cfg, _delete_task(tmp_path), DryRunAdapter(), storage, confirm=lambda *a: "timeout").run("o'chir", "en")
    assert "timed out" in t.final_message


def test_stop_pressed_while_confirming_does_not_execute_even_if_approved(cfg, storage, tmp_path):
    adapter = DryRunAdapter()
    agent = Agent(cfg, _delete_task(tmp_path), adapter, storage)

    def confirm(*_a):
        agent.stop()          # foydalanuvchi to'xtatishni bosdi, keyin dialogda "Ha" ni bosdi
        return True

    agent.confirm = confirm
    t = agent.run("o'chir")
    assert adapter.executed == [] and t.status == TaskStatus.cancelled


def test_blocked_action_never_reaches_confirmation(cfg, storage):
    asked = []
    p = ScriptedProvider([{"action": {"type": "delete_path", "path": "/etc/hosts"}}])
    adapter = DryRunAdapter()
    Agent(cfg, p, adapter, storage, confirm=lambda *a: asked.append(1) or True).run("o'chir")
    assert asked == [] and adapter.executed == []


def test_mode_b_denied_step_not_executed_and_reports_denial(cfg, storage, tmp_path):
    adapter = DryRunAdapter()
    plan = {"steps": [{"action": {"type": "delete_path", "path": str(tmp_path / "x")}},
                      {"action": {"type": "open_app", "app": "Notes"}}]}
    from xadicha.models import Mode

    t = Agent(cfg, ScriptedProvider(plan=plan), adapter, storage, confirm=lambda *a: False).run("x", mode=Mode.llm_plan)
    assert adapter.executed == [] and t.status == TaskStatus.failed and "rad" in t.final_message.lower()


# ---------------------------------------------------------------- xizmat va API: tasdiq jarayoni

def make(cfg, storage, provider, timeout=5.0):
    svc = XadichaService(cfg, provider=provider, adapter=DryRunAdapter(), storage=storage, confirm_timeout=timeout)
    return TestClient(create_app(svc)), svc


def wait_pending(client, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        p = client.get("/api/status").json()["pending_confirmation"]
        if p:
            return p
        time.sleep(0.02)
    raise AssertionError("tasdiq so'rovi kelmadi")


def wait_idle(svc, timeout=5.0):
    end = time.time() + timeout
    time.sleep(0.05)
    while svc.busy and time.time() < end:
        time.sleep(0.02)
    assert not svc.busy


def test_api_approval_executes_once(cfg, storage, tmp_path):
    client, svc = make(cfg, storage, _delete_task(tmp_path))
    client.post("/api/tasks", json={"instruction": "o'chir"})
    p = wait_pending(client)
    assert {"id", "expires_at"} <= set(p)
    r = client.post(f"/api/tasks/{p['task_id']}/confirm", json={"approve": True, "confirmation_id": p["id"]})
    assert r.status_code == 200
    wait_idle(svc)
    assert len(svc.adapter.executed) == 1
    assert client.get("/api/tasks").json()[0]["status"] == "success"


def test_api_duplicate_answer_is_rejected_and_first_wins(cfg, storage, tmp_path):
    client, svc = make(cfg, storage, _delete_task(tmp_path))
    gate = threading.Event()
    real_confirm = svc._confirm

    def slow_confirm(*a):
        # tasdiq qabul qilingandan keyin agent davom etishidan oldin ikkinchi javobni yuborishga ulguramiz
        res = real_confirm(*a)
        gate.wait(2)
        return res

    svc.agent.confirm = slow_confirm
    client.post("/api/tasks", json={"instruction": "o'chir"})
    p = wait_pending(client)
    url = f"/api/tasks/{p['task_id']}/confirm"
    assert client.post(url, json={"approve": False, "confirmation_id": p["id"]}).status_code == 200
    second = client.post(url, json={"approve": True, "confirmation_id": p["id"]})
    gate.set()
    assert second.status_code in (404, 409)   # 409 — hali ochiq, 404 — allaqachon yopilgan
    wait_idle(svc)
    assert svc.adapter.executed == []


def test_api_late_answer_after_timeout_is_404_and_not_executed(cfg, storage, tmp_path):
    client, svc = make(cfg, storage, _delete_task(tmp_path), timeout=0.3)
    client.post("/api/tasks", json={"instruction": "o'chir"})
    p = wait_pending(client)
    wait_idle(svc)
    r = client.post(f"/api/tasks/{p['task_id']}/confirm", json={"approve": True, "confirmation_id": p["id"]})
    assert r.status_code == 404
    assert svc.adapter.executed == []
    t = client.get("/api/tasks").json()[0]
    assert t["status"] == "cancelled" and "muddati" in t["steps"][0]["detail"]


def test_api_stale_confirmation_id_is_rejected(cfg, storage, tmp_path):
    client, svc = make(cfg, storage, _delete_task(tmp_path))
    client.post("/api/tasks", json={"instruction": "o'chir"})
    p = wait_pending(client)
    r = client.post(f"/api/tasks/{p['task_id']}/confirm", json={"approve": True, "confirmation_id": "eski-id"})
    assert r.status_code == 404
    client.post("/api/stop")
    wait_idle(svc)
    assert svc.adapter.executed == []


def test_api_emergency_stop_during_confirmation(cfg, storage, tmp_path):
    client, svc = make(cfg, storage, _delete_task(tmp_path))
    events = []
    svc.subscribe(events.append)
    client.post("/api/tasks", json={"instruction": "o'chir"})
    wait_pending(client)
    assert client.post("/api/stop").status_code == 200
    wait_idle(svc)
    assert svc.adapter.executed == []
    t = client.get("/api/tasks").json()[0]
    assert t["status"] == "cancelled"
    resolved = [e for e in events if e["type"] == "confirm_resolved"]
    assert resolved and resolved[0]["outcome"] == "cancelled" and resolved[0]["approved"] is False


def test_two_fast_task_requests_only_one_starts(cfg, storage):
    # Avval: ikkala so'rov ham 202 olib, ikkinchi ip ichida RuntimeError chiqarardi
    started = threading.Event()
    release = threading.Event()

    class Slow(ScriptedProvider):
        def decide(self, *a, **k):
            started.set()
            release.wait(3)
            return super().decide(*a, **k)

    client, svc = make(cfg, storage, Slow([{"done": True, "success": True}]))
    codes = [client.post("/api/tasks", json={"instruction": "a"}).status_code for _ in range(2)]
    release.set()
    wait_idle(svc)
    assert sorted(codes) == [202, 409]
    assert len(client.get("/api/tasks").json()) == 1


# ---------------------------------------------------------------- WebSocket

def test_ws_ignores_malformed_client_messages_and_answers_ping(cfg, storage):
    client, svc = make(cfg, storage, ScriptedProvider([{"done": True, "success": True}]))
    with client.websocket_connect("/api/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and "listening" in hello["status"]
        ws.send_text("{not json")
        ws.send_text("[1,2,3]")
        ws.send_text('{"type": "ping"}')
        assert ws.receive_json()["type"] == "pong"
    assert svc.listeners == []   # uzilgandan keyin obuna tozalangan


def test_ws_disconnect_unsubscribes_without_waiting_for_event(cfg, storage):
    client, svc = make(cfg, storage, ScriptedProvider())
    for _ in range(3):
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()
    assert svc.listeners == []


def test_status_reports_honest_capabilities(cfg, storage):
    client, _ = make(cfg, storage, ScriptedProvider())
    caps = client.get("/api/status").json()["capabilities"]
    assert caps["ocr"] is False and caps["accessibility_tree"] is False


# ---------------------------------------------------------------- mikrofon

class FakeListener:
    engine = "fake"

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.transcribed = 0

    def warmup(self):
        pass

    def record_until(self, stop, max_seconds=30.0, on_level=None):
        if self.error:
            raise self.error
        while not stop.wait(0.02):
            if on_level:
                on_level(0.5)
        return np.ones(16_000, dtype=np.float32)

    def transcribe(self, audio, language=None):
        self.transcribed += 1
        return Transcript("Notes ni och", language or "uz", 1.0, True)


def test_listening_state_and_levels_come_from_backend(cfg, storage):
    client, svc = make(cfg, storage, ScriptedProvider())
    svc.listener = FakeListener()
    events = []
    svc.subscribe(events.append)
    assert client.post("/api/listen/start?language=uz").json()["state"] == "recording"
    assert client.get("/api/status").json()["listening"] == "recording"
    time.sleep(0.2)
    r = client.post("/api/listen/stop").json()
    assert r["text"] == "Notes ni och"
    assert svc.listening == "idle"
    assert any(e["type"] == "mic_level" for e in events)
    states = [e["state"] for e in events if e["type"] == "listening"]
    assert states[0] == "recording" and states[-1] == "idle" and "transcribing" in states


def test_microphone_error_is_reported_clearly(cfg, storage):
    client, svc = make(cfg, storage, ScriptedProvider())
    svc.listener = FakeListener(error=RuntimeError("Error querying device -1: No default input device"))
    client.post("/api/listen/start")
    time.sleep(0.1)
    r = client.post("/api/listen/stop")
    assert r.status_code == 503 and "Mikrofon topilmadi" in r.json()["detail"]
    assert svc.listening == "idle"


def test_stop_listening_without_start_is_409(cfg, storage):
    client, _ = make(cfg, storage, ScriptedProvider())
    assert client.post("/api/listen/stop").status_code == 409


def test_emergency_stop_cancels_recording_without_transcribing(cfg, storage):
    client, svc = make(cfg, storage, ScriptedProvider())
    fake = FakeListener()
    svc.listener = fake
    client.post("/api/listen/start")
    time.sleep(0.05)
    client.post("/api/stop")
    svc._listen_thread.join(2)
    assert fake.transcribed == 0 and svc.listening == "idle"


def test_mic_error_messages():
    assert "ruxsat" in mic_error_message(RuntimeError("PortAudio error -9986: permission denied"))
    assert "topilmadi" in mic_error_message(RuntimeError("Invalid device"))


def test_rms_level_range():
    assert rms_level(np.zeros(100, dtype=np.float32)) == 0.0
    assert rms_level(np.ones(100, dtype=np.float32)) == 1.0
    assert 0 < rms_level(np.full(100, 0.05, dtype=np.float32)) < 1


# ---------------------------------------------------------------- kirill yozuvi

@pytest.mark.parametrize("text,app", [
    ("Сафари ни оч", "Safari"), ("Телеграмни оч", "Telegram"), ("Почта ни оч", "Mail"), ("Открой Notes", "Notes"),
])
def test_cyrillic_open_app(text, app):
    intent, actions, _ = parse_command(text, "uz")
    assert intent == "open_app" and actions[0].app == app


def test_uzbek_cyrillic_create_folder():
    intent, actions, _ = parse_command('"Ҳисобот" папка яратинг', "uz")
    assert intent == "create_folder" and actions[0].path.endswith("Ҳисобот")
