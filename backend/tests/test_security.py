"""Mahalliy API xavfsizligi: Host (DNS rebinding), Origin (CSRF), sessiya kaliti, WebSocket, validatsiya, log.

Simulyatsiya: dry-run adapter, soxta model. Real tarmoq hujumi o'tkazilmaydi.
"""

from __future__ import annotations

import logging

import pytest
from conftest import ScriptedProvider, api_client
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from xadicha.adapters.base import DryRunAdapter
from xadicha.service import RedactFilter, XadichaService, redact

EVIL = "https://evil.example"


@pytest.fixture
def svc(cfg, storage):
    return XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage)


@pytest.fixture
def client(svc):
    return api_client(svc)


def test_cross_site_post_is_rejected_and_not_executed(client, svc):
    stopped = []
    svc.stop = lambda: stopped.append(1)
    r = client.post("/api/stop", headers={"Origin": EVIL, "content-type": "text/plain"})
    assert r.status_code == 403 and stopped == []


def test_cross_site_cannot_start_microphone(client, svc):
    started = []
    svc.start_listening = lambda *a: started.append(1) or "recording"
    assert client.post("/api/listen/start", headers={"Origin": EVIL}).status_code == 403
    assert started == []


def test_missing_or_wrong_token_is_401(client):
    assert client.get("/api/status", headers={"x-xadicha-token": ""}).status_code == 401
    assert client.get("/api/status", headers={"x-xadicha-token": "guess"}).status_code == 401
    assert client.get("/api/status").status_code == 200


def test_dns_rebinding_host_is_rejected(svc):
    c = TestClient(api_client(svc).app, base_url="http://attacker.example:8765")
    assert c.get("/api/session").status_code == 400


def test_session_token_not_given_to_other_origins(client):
    assert client.get("/api/session", headers={"Origin": EVIL}).status_code == 403
    r = client.get("/api/session", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight_from_other_origin_not_allowed(client):
    r = client.options("/api/tasks", headers={"Origin": EVIL, "Access-Control-Request-Method": "POST",
                                              "Access-Control-Request-Headers": "x-xadicha-token"})
    assert "access-control-allow-origin" not in r.headers


def test_token_differs_per_process(svc):
    assert api_client(svc).token != api_client(svc).token


@pytest.mark.parametrize("headers,query", [
    ({"Origin": EVIL}, "TOKEN"), ({}, ""), ({}, "wrong"), ({"host": "attacker.example"}, "TOKEN"),
])
def test_websocket_rejects_bad_origin_host_or_token(client, headers, query):
    q = client.token if query == "TOKEN" else query
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"ws://127.0.0.1:8765/api/ws?token={q}", headers=headers) as ws:
            ws.receive_json()


def test_websocket_accepts_local_origin(client):
    with client.websocket_connect(f"ws://127.0.0.1:8765/api/ws?token={client.token}",
                                  headers={"Origin": "http://localhost:3000"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_request_validation(client):
    assert client.post("/api/tasks", json={"instruction": "x" * 2001}).status_code == 422
    assert client.post("/api/tasks", json={"instruction": "a", "language": "tr"}).status_code == 422
    assert client.post("/api/tasks", json={"instruction": "a", "mode": "Z"}).status_code == 422
    assert client.get("/api/tasks?limit=0").status_code == 422
    assert client.get("/api/tasks?limit=100000").status_code == 422
    assert client.post("/api/understand", json={"text": ""}).status_code == 422


def test_openapi_docs_disabled(client):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_secrets_are_redacted():
    s = redact("key sk-ant-api03-abcdefghijklmnop and Bearer abcdefghijkl token=xyz123 ANTHROPIC_API_KEY=sk-ant-zzzzzzzzzzzz")
    assert "abcdefghijklmnop" not in s and "abcdefghijkl" not in s and "xyz123" not in s and "zzzz" not in s
    assert redact("data:image/jpeg;base64," + "A" * 100) == "data:image/***"


def test_log_filter_redacts_args():
    rec = logging.LogRecord("xadicha", logging.WARNING, __file__, 1, "reply %r", ("sk-ant-secretsecret123",), None)
    RedactFilter().filter(rec)
    assert "secretsecret123" not in rec.getMessage()
