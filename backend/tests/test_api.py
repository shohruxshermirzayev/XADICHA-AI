import time

from conftest import ScriptedProvider
from fastapi.testclient import TestClient

from xadicha.adapters.base import DryRunAdapter
from xadicha.api import create_app
from xadicha.service import XadichaService


def make_client(cfg, storage, provider):
    svc = XadichaService(cfg, provider=provider, adapter=DryRunAdapter(), storage=storage, confirm_timeout=5)
    return TestClient(create_app(svc)), svc


def wait_idle(svc, timeout=5):
    end = time.time() + timeout
    time.sleep(0.05)
    while svc.busy and time.time() < end:
        time.sleep(0.02)


def test_status_has_no_secret(cfg, storage):
    cfg.anthropic_api_key = "sk-secret-123"
    client, _ = make_client(cfg, storage, ScriptedProvider())
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["adapter"] == "dry-run" and body["config"]["has_api_key"] is True
    assert "sk-secret-123" not in r.text


def test_task_lifecycle(cfg, storage):
    p = ScriptedProvider([{"action": {"type": "open_app", "app": "Notes"}},
                          {"previous_step_ok": True, "done": True, "success": True, "final_message": "ok"}])
    client, svc = make_client(cfg, storage, p)
    assert client.post("/api/tasks", json={"instruction": "Notes ni och"}).status_code == 202
    wait_idle(svc)
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 1 and tasks[0]["status"] == "success"
    assert client.get(f"/api/tasks/{tasks[0]['id']}").json()["steps"][0]["action"]["app"] == "Notes"
    assert client.get("/api/status").json()["stats"]["success"] == 1


def test_empty_instruction_rejected(cfg, storage):
    client, _ = make_client(cfg, storage, ScriptedProvider())
    assert client.post("/api/tasks", json={"instruction": "  "}).status_code == 400


def test_confirmation_over_api(cfg, storage, tmp_path):
    p = ScriptedProvider([{"action": {"type": "delete_path", "path": str(tmp_path / "x")}},
                          {"previous_step_ok": True, "done": True, "success": True}])
    client, svc = make_client(cfg, storage, p)
    client.post("/api/tasks", json={"instruction": "o'chir"})
    for _ in range(100):
        pending = client.get("/api/status").json()["pending_confirmation"]
        if pending:
            break
        time.sleep(0.02)
    assert pending and pending["risk"] == "high"
    assert client.post(f"/api/tasks/{pending['task_id']}/confirm", json={"approve": False}).status_code == 200
    wait_idle(svc)
    assert client.get("/api/tasks").json()[0]["status"] == "cancelled"


def test_websocket_events(cfg, storage):
    p = ScriptedProvider([{"done": True, "success": True, "final_message": "salom"}])
    client, svc = make_client(cfg, storage, p)
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/tasks", json={"instruction": "salom"})
        kinds = []
        for _ in range(10):
            e = ws.receive_json()
            kinds.append(e["type"])
            if e["type"] == "task_finished":
                break
        assert kinds[0] == "task_started" and kinds[-1] == "task_finished"


def test_history_clear(cfg, storage):
    client, svc = make_client(cfg, storage, ScriptedProvider([{"done": True, "success": True}]))
    client.post("/api/tasks", json={"instruction": "a"})
    wait_idle(svc)
    assert client.delete("/api/history").json()["deleted"] == 1
