"""Ekran holati (Screen Intelligence paneli) — simulyatsiya: soxta adapter, OCR va accessibility."""

from __future__ import annotations

from PIL import Image

from conftest import ScriptedProvider, api_client
from xadicha.adapters.base import DryRunAdapter
from xadicha.service import XadichaService
from xadicha.vision.context import TextBox, UIElement


class FakeMac(DryRunAdapter):
    name = "macos"

    def frontmost_app(self) -> str:
        return "Notes"

    def front_window_title(self) -> str:
        return "Bugungi rejalar"

    def screen_size(self):
        return (200, 100)


class FakeOCR:
    def availability(self):
        return ("not_tested", "")

    def recognize(self, image, size):
        return [TextBox("Pastda", 0.8, 10, 60, 40, 10), TextBox("Sarlavha", 0.95, 10, 5, 50, 10)]


class FakeAX:
    def availability(self):
        return ("not_tested", "")

    def snapshot(self, max_nodes: int = 150):
        return [UIElement("AXButton", "Yangi eslatma", 5, 5, 20, 10)]


def test_dry_run_snapshot_is_honest(cfg):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter())
    snap = svc.screen_snapshot()
    assert snap["available"] is False and snap["preview"] is None and "dry-run" in snap["error"]


def test_snapshot_returns_context_without_saving(cfg, monkeypatch, tmp_path):
    import xadicha.vision.screen as screen

    monkeypatch.setattr(screen, "capture_image", lambda size=None: (Image.new("RGB", (400, 200), "white"), 200, 100))
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=FakeMac(), ocr=FakeOCR(), accessibility=FakeAX())
    snap = svc.screen_snapshot()
    assert snap["app"] == "Notes" and snap["window"] == "Bugungi rejalar"
    assert snap["preview"].startswith("data:image/jpeg;base64,")
    assert [x["text"] for x in snap["ocr"]["lines"]] == ["Sarlavha", "Pastda"]   # yuqoridan pastga
    assert snap["ax"]["elements"][0]["name"] == "Yangi eslatma"
    assert not any(p.suffix in (".png", ".jpg", ".jpeg") for p in tmp_path.rglob("*"))


def test_snapshot_reports_permission_error(cfg, monkeypatch):
    import xadicha.vision.screen as screen

    def denied(size=None):
        raise PermissionError("Screen Recording ruxsati yo'q")

    monkeypatch.setattr(screen, "capture_image", denied)
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=FakeMac(), ocr=FakeOCR(), accessibility=FakeAX())
    snap = svc.screen_snapshot()
    assert snap["preview"] is None and "PermissionError" in snap["error"]


def test_snapshot_endpoint_requires_token(cfg):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter())
    client = api_client(svc)
    assert client.post("/api/screen/snapshot", json={"preview": False}).json()["available"] is False
    del client.headers["x-xadicha-token"]
    assert client.post("/api/screen/snapshot", json={}).status_code == 401
