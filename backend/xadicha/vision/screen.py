"""Ekranni suratga olish.

Rasm pyautogui koordinatalari (mantiqiy nuqtalar) o'lchamiga keltiriladi,
shunda model qaytargan (x, y) to'g'ridan-to'g'ri bosish uchun yaraydi —
Retina ekranda ham.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field

import mss
from PIL import Image

MAX_SIDE = 1280  # modelga yuboriladigan rasmning eng uzun tomoni


@dataclass
class Screenshot:
    png_base64: str  # (nomi tarixiy) — base64 kodlangan rasm; formati media_type'da
    width: int       # modelga yuborilgan rasm o'lchami
    height: int
    scale: float     # rasm koordinatasi * scale = ekran koordinatasi (mantiqiy nuqta) — agent.py qo'llaydi
    media_type: str = "image/jpeg"
    context: str = ""   # OCR / accessibility daraxtidan matnli kontekst (bo'lsa)
    logical_w: int = 0
    logical_h: int = 0
    timings: dict[str, int] = field(default_factory=dict)   # capture / encode / ocr / ax (ms) — tezlik tahlili


def capture_image(logical_size: tuple[int, int] | None = None) -> tuple[Image.Image, int, int]:
    """Asosiy monitor surati (to'liq piksel o'lchamida) va mantiqiy o'lcham. Diskka yozilmaydi."""
    if logical_size is None:
        import pyautogui

        logical_size = pyautogui.size()
    lw, lh = int(logical_size[0]), int(logical_size[1])
    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    return img, lw, lh


def capture(logical_size: tuple[int, int] | None = None, max_side: int = MAX_SIDE) -> Screenshot:
    img, lw, lh = capture_image(logical_size)
    return encode(img, lw, lh, max_side)


def to_screen(x: float, y: float, shot: Screenshot) -> tuple[int, int]:
    """Model qaytargan rasm koordinatasini mantiqiy ekran nuqtasiga o'tkazadi va ekran chegarasida ushlaydi."""
    sx, sy = round(x * shot.scale), round(y * shot.scale)
    if shot.logical_w and shot.logical_h:
        sx = min(max(sx, 0), shot.logical_w - 1)
        sy = min(max(sy, 0), shot.logical_h - 1)
    return sx, sy


def encode(img: Image.Image, logical_w: int, logical_h: int, max_side: int = MAX_SIDE) -> Screenshot:
    img = img.resize((logical_w, logical_h))
    factor = min(1.0, max_side / max(logical_w, logical_h))
    w, h = round(logical_w * factor), round(logical_h * factor)
    if factor < 1.0:
        img = img.resize((w, h))
    buf = io.BytesIO()
    # JPEG: PNG(optimize)'dan ~50 baravar tez kodlanadi va ~4 baravar kichik (o'lchangan: 4 ms / 200 ms)
    img.save(buf, format="JPEG", quality=80)
    return Screenshot(
        png_base64=base64.b64encode(buf.getvalue()).decode(),
        width=w,
        height=h,
        scale=1.0 / factor,
        media_type="image/jpeg",
        logical_w=logical_w,
        logical_h=logical_h,
    )
