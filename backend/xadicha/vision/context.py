"""Ekran kontekstining matnli manbalari: OCR va accessibility daraxti (ixtiyoriy).

Muhim farq:
  - Ekran surati + vision model — rasmga qarab taxmin (agent.py, vision/screen.py).
  - OCR — rasmdagi matnni koordinata va ishonch bilan aniq o'qish (bu yerda: Apple Vision, macOS).
  - Accessibility daraxti — ilovaning o'zi e'lon qilgan UI elementlari (rol, nom, joylashuv) — macOS AXUIElement.
Ular bir-birining o'rnini bosmaydi. Har bir provayder o'z mavjudligini halol bildiradi.

macOS uchun ixtiyoriy kutubxonalar: `pip install -r requirements-macos-optional.txt`
(pyobjc-framework-Vision, pyobjc-framework-ApplicationServices). Real Mac'da hali sinalmagan.
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# Holat qiymatlari (interfeys bilan bir xil)
AVAILABLE, UNAVAILABLE, NOT_TESTED, NOT_IMPLEMENTED = "available", "unavailable", "not_tested", "not_implemented"


@dataclass
class TextBox:
    text: str
    confidence: float
    x: int        # mantiqiy ekran nuqtalarida (pyautogui bilan bir xil koordinatalar)
    y: int
    w: int
    h: int


@dataclass
class UIElement:
    role: str
    name: str
    x: int
    y: int
    w: int
    h: int
    enabled: bool = True


# ------------------------------------------------------------------ OCR

class OCRProvider(ABC):
    name = "base"

    @abstractmethod
    def availability(self) -> tuple[str, str]:
        """(holat, izoh)"""

    @abstractmethod
    def recognize(self, image: Any, logical_size: tuple[int, int]) -> list[TextBox]:
        """PIL rasmidan matn qutilarini qaytaradi (mantiqiy nuqtalarda)."""


class NullOCR(OCRProvider):
    name = "none"

    def __init__(self, reason: str = "OCR provayderi yo'q"):
        self.reason = reason

    def availability(self) -> tuple[str, str]:
        return UNAVAILABLE, self.reason

    def recognize(self, image: Any, logical_size: tuple[int, int]) -> list[TextBox]:
        return []


def vision_bbox_to_logical(bbox: tuple[float, float, float, float], logical_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Apple Vision normallashgan qutisi (x, y, w, h; boshlanish — PASTKI chap burchak) → mantiqiy (x, y, w, h)
    yuqori chapdan."""
    bx, by, bw, bh = bbox
    lw, lh = logical_size
    x = round(bx * lw)
    y = round((1.0 - by - bh) * lh)
    return x, y, round(bw * lw), round(bh * lh)


class AppleVisionOCR(OCRProvider):
    """macOS Vision framework (VNRecognizeTextRequest) — lokal, bepul. O'zbek tili alohida qo'llab-quvvatlanmaydi;
    lotin yozuvi ingliz modeli bilan, kirill — rus modeli bilan o'qiladi (aniqligi o'lchanmagan)."""

    name = "apple-vision"
    LANGS = ["en-US", "ru-RU"]

    def __init__(self):
        self._err = ""
        try:
            import Quartz  # noqa: F401
            import Vision  # noqa: F401
        except Exception as e:  # noqa: BLE001
            self._err = f"pyobjc-framework-Vision o'rnatilmagan ({e.__class__.__name__})"

    def availability(self) -> tuple[str, str]:
        if self._err:
            return UNAVAILABLE, self._err
        return NOT_TESTED, "Apple Vision OCR yozilgan; real Mac'da sinalmagan"

    def recognize(self, image: Any, logical_size: tuple[int, int]) -> list[TextBox]:
        if self._err:
            return []
        import io

        import Vision
        from Foundation import NSData

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        raw = buf.getvalue()
        data = NSData.dataWithBytes_length_(raw, len(raw))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setRecognitionLanguages_(self.LANGS)
        req.setUsesLanguageCorrection_(False)
        ok, _err = handler.performRequests_error_([req], None)
        if not ok:
            return []
        out: list[TextBox] = []
        for obs in req.results() or []:
            cands = obs.topCandidates_(1)
            if not cands:
                continue
            c = cands[0]
            b = obs.boundingBox()
            x, y, w, h = vision_bbox_to_logical((b.origin.x, b.origin.y, b.size.width, b.size.height), logical_size)
            out.append(TextBox(str(c.string()), float(c.confidence()), x, y, w, h))
        return out


# ------------------------------------------------------------------ Accessibility daraxti

_INTERACTIVE = {"AXButton", "AXTextField", "AXTextArea", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXCheckBox",
                "AXRadioButton", "AXPopUpButton", "AXComboBox", "AXTab", "AXSearchField", "AXSlider", "AXCell"}


class AccessibilityProvider(ABC):
    name = "base"

    @abstractmethod
    def availability(self) -> tuple[str, str]: ...

    @abstractmethod
    def snapshot(self, max_nodes: int = 150) -> list[UIElement]:
        """Old plandagi ilovaning interaktiv elementlari."""


class NullAccessibility(AccessibilityProvider):
    name = "none"

    def __init__(self, reason: str = "Accessibility provayderi yo'q"):
        self.reason = reason

    def availability(self) -> tuple[str, str]:
        return UNAVAILABLE, self.reason

    def snapshot(self, max_nodes: int = 150) -> list[UIElement]:
        return []


class AXApi(ABC):
    """AXUIElement ustidagi yupqa qatlam — testlarda soxta daraxt bilan almashtiriladi."""

    @abstractmethod
    def trusted(self) -> bool: ...

    @abstractmethod
    def root(self) -> Any: ...

    @abstractmethod
    def attr(self, element: Any, name: str) -> Any: ...


class _PyObjCAXApi(AXApi):
    def __init__(self):
        import ApplicationServices as AS  # noqa: N814
        from AppKit import NSWorkspace

        self.AS, self.ws = AS, NSWorkspace

    def trusted(self) -> bool:
        return bool(self.AS.AXIsProcessTrusted())

    def root(self) -> Any:
        app = self.ws.sharedWorkspace().frontmostApplication()
        return self.AS.AXUIElementCreateApplication(app.processIdentifier()) if app else None

    def attr(self, element: Any, name: str) -> Any:
        err, value = self.AS.AXUIElementCopyAttributeValue(element, name, None)
        if err != 0:
            return None
        if name in ("AXPosition", "AXSize") and value is not None:
            kind = self.AS.kAXValueCGPointType if name == "AXPosition" else self.AS.kAXValueCGSizeType
            ok, v = self.AS.AXValueGetValue(value, kind, None)
            if not ok:
                return None
            return (v.x, v.y) if name == "AXPosition" else (v.width, v.height)
        return value


def walk_ax(api: AXApi, max_nodes: int = 150, max_depth: int = 12) -> list[UIElement]:
    """Daraxtni kenglik bo'yicha aylanadi; faqat interaktiv yoki nomli elementlarni qaytaradi."""
    root = api.root()
    if root is None:
        return []
    out: list[UIElement] = []
    queue: list[tuple[Any, int]] = [(root, 0)]
    visited = 0
    while queue and len(out) < max_nodes and visited < max_nodes * 10:
        el, depth = queue.pop(0)
        visited += 1
        role = str(api.attr(el, "AXRole") or "")
        name = str(api.attr(el, "AXTitle") or api.attr(el, "AXDescription") or api.attr(el, "AXValue") or "").strip()
        pos, size = api.attr(el, "AXPosition"), api.attr(el, "AXSize")
        if role in _INTERACTIVE or (role == "AXStaticText" and name):
            if pos and size and size[0] > 0 and size[1] > 0:
                enabled = api.attr(el, "AXEnabled")
                out.append(UIElement(role, name[:80], round(pos[0]), round(pos[1]), round(size[0]), round(size[1]),
                                     enabled is not False))
        if depth < max_depth:
            for child in api.attr(el, "AXChildren") or []:
                queue.append((child, depth + 1))
    return out


class MacAccessibility(AccessibilityProvider):
    """macOS AXUIElement MVP: old plandagi ilova elementlari. Accessibility ruxsati kerak. Real Mac'da sinalmagan."""

    name = "macos-ax"

    def __init__(self, api: AXApi | None = None):
        self._err = ""
        self.api = api
        if api is None:
            try:
                self.api = _PyObjCAXApi()
            except Exception as e:  # noqa: BLE001
                self._err = f"pyobjc-framework-ApplicationServices o'rnatilmagan ({e.__class__.__name__})"

    def availability(self) -> tuple[str, str]:
        if self._err or self.api is None:
            return UNAVAILABLE, self._err or "API yo'q"
        try:
            trusted = self.api.trusted()
        except Exception as e:  # noqa: BLE001
            return UNAVAILABLE, f"AX xatosi: {e.__class__.__name__}"
        if not trusted:
            return UNAVAILABLE, "Accessibility ruxsati berilmagan (System Settings → Privacy & Security → Accessibility)"
        return NOT_TESTED, "AXUIElement MVP yozilgan; real Mac'da sinalmagan"

    def snapshot(self, max_nodes: int = 150) -> list[UIElement]:
        if self.availability()[0] in (UNAVAILABLE,):
            return []
        try:
            return walk_ax(self.api, max_nodes)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return []


# ------------------------------------------------------------------ yig'ish

def make_ocr() -> OCRProvider:
    if platform.system() != "Darwin":
        return NullOCR("OCR faqat macOS (Apple Vision) uchun yozilgan; Windows OCR amalga oshirilmagan")
    return AppleVisionOCR()


def make_accessibility() -> AccessibilityProvider:
    if platform.system() == "Darwin":
        return MacAccessibility()
    if platform.system() == "Windows":
        return NullAccessibility("Windows UI Automation amalga oshirilmagan")
    return NullAccessibility("Bu tizimda accessibility provayderi yo'q")


def summarize(texts: list[TextBox], elements: list[UIElement], factor: float = 1.0, max_lines: int = 60) -> str:
    """Model uchun qisqa matnli kontekst. factor = 1/scale: koordinatalar ekran surati (rasm) fazosiga
    o'tkaziladi — model bosish koordinatalarini ham shu fazoda qaytaradi, agent esa ularni qayta masshtablaydi."""
    def c(v: float) -> int:
        return round(v * factor)

    lines: list[str] = []
    if elements:
        lines.append("UI elements from the accessibility tree (role, name, centre x,y in screenshot coordinates):")
        for e in elements[: max_lines // 2]:
            flag = "" if e.enabled else " [disabled]"
            lines.append(f"- {e.role} \"{e.name}\" @({c(e.x + e.w / 2)},{c(e.y + e.h / 2)}){flag}")
    if texts:
        lines.append("Text read by OCR (text, confidence, centre x,y in screenshot coordinates):")
        for t in sorted(texts, key=lambda b: (b.y, b.x))[: max(0, max_lines - len(lines))]:
            lines.append(f"- \"{t.text[:80]}\" {t.confidence:.2f} @({c(t.x + t.w / 2)},{c(t.y + t.h / 2)})")
    return "\n".join(lines)
