"""Ekran tushunish: koordinata masshtabi, OCR va accessibility provayder interfeysi (simulyatsiya — soxta API).

Real Apple Vision va AXUIElement bu testlarda ishlatilmaydi: ular faqat macOS'da, pyobjc bilan ishlaydi
(docs/MACOS_TEST_PROTOCOL.md).
"""

from __future__ import annotations

from conftest import ScriptedProvider
from PIL import Image

from xadicha.adapters.base import DryRunAdapter
from xadicha.agent import Agent
from xadicha.service import XadichaService
from xadicha.vision import context as ctx
from xadicha.vision.screen import encode, to_screen


def _shot():
    return encode(Image.new("RGB", (3024, 1964)), 1512, 982, 1024)   # M2 Pro Retina, mantiqiy 1512x982


def test_model_click_is_scaled_to_screen_points(cfg, storage):
    # Xato: Screenshot.scale hech qayerda qo'llanmasdi — bosishlar ~32% chap-yuqoriga siljirdi
    shot = _shot()
    p = ScriptedProvider([{"action": {"type": "click", "x": 512, "y": 333}},
                          {"previous_step_ok": True, "done": True, "success": True}])
    ad = DryRunAdapter()
    Agent(cfg, p, ad, storage, screen_fn=lambda: shot).run("bos")
    assert (ad.executed[0].x, ad.executed[0].y) == (756, 492)


def test_to_screen_clamps_to_display():
    shot = _shot()
    assert to_screen(5000, -10, shot) == (1511, 0)


def test_apple_vision_bbox_conversion():
    # Vision: normallashgan, boshlanish pastki chapda
    assert ctx.vision_bbox_to_logical((0.1, 0.8, 0.2, 0.1), (1000, 500)) == (100, 50, 200, 50)


class FakeAX(ctx.AXApi):
    def __init__(self, trusted=True):
        self._trusted = trusted
        btn = {"AXRole": "AXButton", "AXTitle": "Yuborish", "AXPosition": (100, 200), "AXSize": (80, 30)}
        hidden = {"AXRole": "AXButton", "AXTitle": "Nol", "AXPosition": (0, 0), "AXSize": (0, 0)}
        label = {"AXRole": "AXStaticText", "AXValue": "Salom", "AXPosition": (10, 10), "AXSize": (50, 20)}
        group = {"AXRole": "AXGroup", "AXChildren": [btn, hidden, label]}
        self._root = {"AXRole": "AXApplication", "AXChildren": [group]}

    def trusted(self):
        return self._trusted

    def root(self):
        return self._root

    def attr(self, el, name):
        return el.get(name)


def test_accessibility_walk_returns_interactive_named_visible_elements():
    els = ctx.MacAccessibility(api=FakeAX()).snapshot()
    assert [(e.role, e.name) for e in els] == [("AXButton", "Yuborish"), ("AXStaticText", "Salom")]


def test_accessibility_reports_missing_permission():
    ax = ctx.MacAccessibility(api=FakeAX(trusted=False))
    state, detail = ax.availability()
    assert state == "unavailable" and "ruxsat" in detail and ax.snapshot() == []


def test_accessibility_mvp_is_not_tested_not_available():
    assert ctx.MacAccessibility(api=FakeAX()).availability()[0] == "not_tested"


def test_summary_uses_screenshot_coordinates():
    texts = [ctx.TextBox("Login", 0.93, 100, 100, 40, 20)]
    els = [ctx.UIElement("AXButton", "OK", 200, 200, 20, 20)]
    s = ctx.summarize(texts, els, factor=0.5)
    assert '"OK" @(105,105)' in s and '"Login" 0.93 @(60,55)' in s


def test_ocr_unavailable_off_macos_is_reported():
    import platform

    if platform.system() != "Darwin":
        assert ctx.make_ocr().availability()[0] == "unavailable"
        assert ctx.make_accessibility().availability()[0] == "unavailable"


class FakeOCR(ctx.OCRProvider):
    name = "fake"

    def availability(self):
        return "not_tested", "soxta"

    def recognize(self, image, logical_size):
        return [ctx.TextBox("Send", 0.9, 300, 300, 60, 20)]


class TextOnlyProvider(ScriptedProvider):
    supports_vision = False

    def decide(self, instruction, history, screen, language, context=""):
        self.calls.append({"screen": screen, "context": context})
        return super().decide(instruction, history, screen, language)


def test_text_only_model_gets_ocr_context_but_no_image(cfg, storage):
    p = TextOnlyProvider([{"done": True, "success": True}])
    svc = XadichaService(cfg, provider=p, adapter=DryRunAdapter(), storage=storage, ocr=FakeOCR(),
                         screen_fn=lambda: None)
    shot = _shot()
    shot.context = ctx.summarize(FakeOCR().recognize(None, (0, 0)), [], factor=1 / shot.scale)
    svc.agent.screen_fn = lambda: shot
    assert svc.agent.text_context is True
    svc.agent.run("bos")
    mine = [c for c in p.calls if "context" in c][0]
    assert mine["screen"] is None and '"Send"' in mine["context"]


def test_ocr_capability_state_flows_to_status(cfg, storage):
    svc = XadichaService(cfg, provider=ScriptedProvider(), adapter=DryRunAdapter(), storage=storage, ocr=FakeOCR())
    assert svc.status()["capabilities"]["ocr"] == {"state": "not_tested", "detail": "soxta"}
