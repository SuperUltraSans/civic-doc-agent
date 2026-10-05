"""preprocess — 회전 보정, 리사이즈 (지시서 5.1절). 사용자에게 단계로 보이지 않는다.

이미지는 메모리에서만 다룬다. 디스크·로그에 쓰지 않는다.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

from PIL import Image, ImageOps

from app.agent.state import AgentState

MAX_SIDE = 1500
JPEG_QUALITY = 85
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
Image.MAX_IMAGE_PIXELS = 50_000_000  # 압축 폭탄 방지


class UnsupportedImage(Exception):
    pass


def sniff_format(data: bytes) -> str:
    """실제 바이트로 형식을 확인한다 (선언된 Content-Type을 믿지 않음)."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format or ""
            im.verify()
    except Exception as exc:  # Pillow는 형식마다 다른 예외를 던진다
        raise UnsupportedImage(type(exc).__name__) from exc
    if fmt not in ALLOWED_FORMATS:
        raise UnsupportedImage(fmt)
    return fmt


def preprocess_image(data: bytes) -> bytes:
    """EXIF 회전 반영 → 긴 변 1500px 이하 → JPEG 품질 85."""
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            background = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            im = background
        elif im.mode == "L":
            im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()


async def preprocess(state: AgentState) -> dict[str, Any]:
    data = state.get("image_bytes")
    if not data:
        raise UnsupportedImage("no image")
    processed = await asyncio.to_thread(preprocess_image, data)
    return {"image_bytes": processed}
