"""preprocess — 회전 보정, 리사이즈, 사진 품질 사전 점검 (지시서 5.1절). 성공하면 사용자에게 단계로 보이지 않는다.

이미지는 메모리에서만 다룬다. 디스크·로그에 쓰지 않는다.

- 크기: 긴 변 1500px 이하, JPEG 품질 85. 프론트가 이미 그렇게 줄여 보낸 JPEG(메타데이터 없음)는 다시 저장하지 않는다
  (화질 손실·처리 시간 절약). EXIF 등 메타데이터가 있으면 반드시 다시 저장해 지운다 — 촬영 위치(GPS)가 LLM으로 가지 않게.
- 품질 사전 점검: 너무 작음·어두움·밝음·내용 없음·흐림이 숫자로 명백하면 LLM을 부르지 않고 바로 다시 찍기 안내.
  기준은 보수적으로 잡았다(읽을 수 있는 사진은 통과). 측정값은 서버 로그에 남겨 실제 사진으로 다시 맞춘다.
  PHOTO_CHECK_ENABLED=false 로 끌 수 있다.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from app.agent.events import emit_step
from app.agent.state import AgentState
from app.config import get_settings
from app.logging_setup import log_event

MAX_SIDE = 1500
JPEG_QUALITY = 85
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
Image.MAX_IMAGE_PIXELS = 50_000_000  # 압축 폭탄 방지

# 품질 사전 점검 기준 (2026-10-06, 샘플·실사진·인위적 흐림/어둡게 변형으로 측정해 보수적으로 잡음)
#   읽을 수 있던 실제 사진: 선명도 196~5490, 밝기 155~246 / 흐림 반경 3 이상: 선명도 1.4~4.2
MIN_LONG_SIDE = 500  # 긴 변 픽셀
MIN_MEAN = 30  # 밝기 평균 (0~255)
MAX_MEAN = 248  # 이보다 밝으면서 명암 차이가 거의 없으면 너무 밝음
MIN_STD = 6  # 명암 차이 (표준편차)
MIN_SHARPNESS = 10  # 라플라시안 분산 (긴 변 1000px 기준)
# 이 키가 있으면 메타데이터가 있는 것 → 다시 저장해서 지운다
_METADATA_KEYS = ("exif", "xmp", "XML:com.adobe.xmp", "comment", "photoshop", "icc_profile")

RETAKE: dict[str, dict[str, Any]] = {
    "small": {"message": "사진이 너무 작아요", "tips": ["문서를 가까이에서 찍어 주세요", "종이 전체가 화면에 꽉 차게 찍어 주세요"]},
    "dark": {"message": "사진이 너무 어두워요", "tips": ["밝은 곳에서 찍어 주세요", "그림자가 지지 않게 찍어 주세요"]},
    "bright": {"message": "사진이 너무 밝아서 글씨가 안 보여요", "tips": ["빛이 종이에 반사되지 않게 각도를 바꿔 찍어 주세요", "햇빛이 바로 비치지 않는 곳에서 찍어 주세요"]},
    "flat": {"message": "문서가 잘 안 보여요", "tips": ["종이 전체가 보이게 찍어 주세요", "밝은 곳에서 찍어 주세요"]},
    "blurry": {"message": "사진이 흐려요", "tips": ["휴대폰을 움직이지 말고 찍어 주세요", "글씨에 초점이 맞은 뒤 찍어 주세요", "밝은 곳에서 찍어 주세요"]},
}


class UnsupportedImage(Exception):
    pass


@dataclass
class PhotoQuality:
    width: int
    height: int
    mean: float
    std: float
    sharpness: float

    @property
    def problem(self) -> str | None:
        if max(self.width, self.height) < MIN_LONG_SIDE:
            return "small"
        if self.mean < MIN_MEAN:
            return "dark"
        if self.mean > MAX_MEAN and self.std < 2 * MIN_STD:
            return "bright"
        if self.std < MIN_STD:
            return "flat"
        if self.sharpness < MIN_SHARPNESS:
            return "blurry"
        return None

    def describe(self) -> str:
        return f"{self.width}x{self.height}, 밝기 {self.mean:.0f}, 명암 {self.std:.0f}, 선명도 {self.sharpness:.0f}"


def measure(im: Image.Image) -> PhotoQuality:
    """회전 보정한 이미지의 크기·밝기·명암·선명도. 선명도는 긴 변 1000px로 줄인 회색조의 라플라시안 분산."""
    gray = im.convert("L")
    width, height = gray.size
    gray.thumbnail((1000, 1000))
    a = np.asarray(gray, dtype=np.float32)
    lap = a[1:-1, 2:] + a[1:-1, :-2] + a[2:, 1:-1] + a[:-2, 1:-1] - 4 * a[1:-1, 1:-1]
    return PhotoQuality(width=width, height=height, mean=float(a.mean()), std=float(a.std()), sharpness=float(lap.var()) if lap.size else 0.0)


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


def _reusable(im: Image.Image) -> bool:
    """다시 저장하지 않고 그대로 보내도 되는 JPEG인지: 크기·색 공간이 맞고, 회전 정보·메타데이터가 없다."""
    return (
        im.format == "JPEG"
        and max(im.size) <= MAX_SIDE
        and im.mode in ("RGB", "L")
        and not any(k in im.info for k in _METADATA_KEYS)
        and im.getexif().get(0x0112, 1) == 1  # 회전 정보 없음
    )


def preprocess_image(data: bytes) -> tuple[bytes, PhotoQuality, bool]:
    """(보낼 JPEG, 품질 측정값, 원본을 그대로 썼는지). EXIF 회전 반영 → 긴 변 1500px 이하 → JPEG 품질 85."""
    with Image.open(io.BytesIO(data)) as original:
        if _reusable(original):
            original.load()
            return data, measure(original), True
        im = ImageOps.exif_transpose(original)
        if im.mode not in ("RGB", "L"):
            background = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            im = background
        elif im.mode == "L":
            im = im.convert("RGB")
        quality = measure(im)
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)  # 메타데이터 없이 저장된다
        return out.getvalue(), quality, False


async def preprocess(state: AgentState) -> dict[str, Any]:
    data = state.get("image_bytes")
    if not data:
        raise UnsupportedImage("no image")
    processed, quality, reused = await asyncio.to_thread(preprocess_image, data)
    problem = quality.problem if get_settings().photo_check_enabled else None
    log_event(
        "photo check",
        sessionId=state.get("session_id"),
        node="preprocess",
        status=problem or "ok",
        detail=f"{quality.describe()} | {'원본 그대로' if reused else '다시 저장'} {len(data)}→{len(processed)}B",
    )
    if problem:
        step = emit_step(
            state.get("session_id"),
            {
                "id": "photo_check",
                "label": "사진 상태를 확인하고 있어요",
                "status": "failed",
                "detail": f"{quality.describe()} → {problem} (LLM 호출 없이 다시 찍기 안내)",
            },
        )
        return {"image_bytes": None, "retake": RETAKE[problem], "steps": [step]}
    return {"image_bytes": processed}


def route_after_preprocess(state: AgentState) -> str:
    from langgraph.graph import END

    return END if state.get("retake") else "extract"
