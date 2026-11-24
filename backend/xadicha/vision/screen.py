"""Ekranni suratga olish.

Rasm pyautogui koordinatalari (mantiqiy nuqtalar) o'lchamiga keltiriladi,
shunda model qaytargan (x, y) to'g'ridan-to'g'ri bosish uchun yaraydi —
Retina ekranda ham.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import mss
from PIL import Image

MAX_SIDE = 1280  # modelga yuboriladigan rasmning eng uzun tomoni


@dataclass
class Screenshot:
    png_base64: str  # (nomi tarixiy) — base64 kodlangan rasm; formati media_type'da
    width: int       # modelga yuborilgan rasm o'lchami
    height: int
    scale: float     # rasm koordinatasi * scale = ekran koordinatasi (mantiqiy nuqta)
    media_type: str = "image/jpeg"


def capture(logical_size: tuple[int, int] | None = None, max_side: int = MAX_SIDE) -> Screenshot:
    if logical_size is None:
        import pyautogui

        logical_size = pyautogui.size()
    lw, lh = int(logical_size[0]), int(logical_size[1])

    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.rgb)

    return encode(img, lw, lh, max_side)


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
    )
