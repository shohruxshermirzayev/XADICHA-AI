from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xadicha.adapters.base import DryRunAdapter  # noqa: E402
from xadicha.config import Config  # noqa: E402
from xadicha.models import Decision, Plan  # noqa: E402
from xadicha.providers.base import LLMProvider, ProviderError  # noqa: E402
from xadicha.storage import Storage  # noqa: E402


class ScriptedProvider(LLMProvider):
    """Oldindan yozilgan qarorlarni qaytaradi — agent mantiqini model'siz sinash uchun."""

    name = "scripted"

    def __init__(self, decisions: list[dict] | None = None, plan: dict | None = None, fail: bool = False):
        self.decisions = [Decision.model_validate(d) for d in (decisions or [])]
        self._plan = Plan.model_validate(plan) if plan else Plan()
        self.fail = fail
        self.calls: list[dict] = []

    def complete(self, system, user, screen):  # pragma: no cover
        raise NotImplementedError

    def decide(self, instruction, history, screen, language):
        if self.fail:
            raise ProviderError("simulyatsiya: provayder mavjud emas")
        self.calls.append({"history": list(history), "screen": screen})
        return self.decisions.pop(0) if self.decisions else Decision(done=True, final_message="tamom")

    def plan(self, instruction, language):
        if self.fail:
            raise ProviderError("simulyatsiya")
        return self._plan


def api_client(svc, **app_kw):
    """Brauzerdagi interfeys kabi: localhost Host, sessiya kaliti sarlavhada."""
    from fastapi.testclient import TestClient

    from xadicha.api import create_app

    app = create_app(svc, **app_kw)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    client.headers["x-xadicha-token"] = client.get("/api/session").json()["token"]
    client.token = client.headers["x-xadicha-token"]
    return client


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(provider="mock", db_path=tmp_path / "t.db", workspace=tmp_path, confirm_risk="high",
                  max_steps=8, max_retries=2, tts_enabled=False, fast_path=False)


@pytest.fixture
def storage(cfg) -> Storage:
    return Storage(cfg.db_path)


@pytest.fixture
def adapter() -> DryRunAdapter:
    return DryRunAdapter()
