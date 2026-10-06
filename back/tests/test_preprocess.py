"""preprocess — 다시 저장 생략 조건, 메타데이터 제거, 사진 품질 사전 점검."""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageFilter

from app.agent.nodes.preprocess import MAX_SIDE, measure, preprocess_image
from app.config import get_settings
from tests.conftest import jpeg_bytes, parse_sse


def doc_image(size=(1200, 900)) -> Image.Image:
    return Image.open(io.BytesIO(jpeg_bytes(size))).convert("RGB")


def encode(im: Image.Image, fmt="JPEG", **kwargs) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **kwargs)
    return buf.getvalue()


# ── 다시 저장 생략 / 메타데이터 ──
def test_clean_small_jpeg_is_sent_as_is():
    """프론트가 줄여 보낸 JPEG(메타데이터 없음)는 다시 저장하지 않는다."""
    data = encode(doc_image())
    out, quality, reused = preprocess_image(data)
    assert reused is True and out == data
    assert (quality.width, quality.height) == (1200, 900)


def test_exif_is_removed_by_reencoding():
    """촬영 위치 등 EXIF가 있으면 다시 저장해 지운다 (LLM으로 보내지 않음)."""
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # 제조사
    exif[0x8825] = {1: "N", 2: (37.0, 34.0, 0.0)}  # GPS
    out, _, reused = preprocess_image(encode(doc_image(), exif=exif))
    assert reused is False
    with Image.open(io.BytesIO(out)) as im:
        assert "exif" not in im.info and len(im.getexif()) == 0


def test_orientation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # 90도 회전해서 봐야 함
    out, quality, reused = preprocess_image(encode(doc_image((1200, 900)), exif=exif))
    assert reused is False
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (900, 1200)
    assert (quality.width, quality.height) == (900, 1200)


@pytest.mark.parametrize("fmt, size", [("JPEG", (3000, 2000)), ("PNG", (1200, 900)), ("WEBP", (1200, 900))])
def test_large_or_non_jpeg_is_reencoded(fmt, size):
    out, _, reused = preprocess_image(encode(doc_image(size), fmt))
    assert reused is False
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "JPEG" and max(im.size) <= MAX_SIDE


# ── 품질 점검 ──
@pytest.mark.parametrize(
    "make, problem",
    [
        (lambda: doc_image(), None),
        (lambda: doc_image((1500, 1100)).filter(ImageFilter.GaussianBlur(1)), None),  # 약간 흐린 것은 통과 (모델이 판단)
        (lambda: doc_image((400, 300)), "small"),
        (lambda: doc_image().point(lambda v: v * 0.08), "dark"),
        (lambda: Image.new("RGB", (1200, 900), "white"), "bright"),
        (lambda: Image.new("RGB", (1200, 900), (128, 128, 128)), "flat"),
        (lambda: doc_image().filter(ImageFilter.GaussianBlur(6)), "blurry"),
    ],
)
def test_quality_problem(make, problem):
    assert measure(make()).problem == problem


# ── 그래프: 명백히 나쁜 사진은 LLM 호출 없이 바로 다시 찍기 ──
async def test_bad_photo_retakes_before_llm(client, monkeypatch):
    from app.llm import client as llm_client

    def no_llm(*_a, **_k):
        raise AssertionError("LLM을 부르면 안 된다")

    monkeypatch.setattr(llm_client, "_make_client", no_llm)
    r = await client.post("/api/analyze", files={"image": ("a.jpg", jpeg_bytes(blank=True), "image/jpeg")})
    events = parse_sse((await client.get(f"/api/analyze/{r.json()['sessionId']}/events")).text)
    assert [n for n, _ in events] == ["step", "need_retake"]
    assert events[0][1]["id"] == "photo_check" and events[0][1]["status"] == "failed"
    assert events[1][1]["message"] == "사진이 너무 밝아서 글씨가 안 보여요"


async def test_photo_check_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("PHOTO_CHECK_ENABLED", "false")
    get_settings.cache_clear()
    r = await client.post("/api/analyze", files={"image": ("a.jpg", jpeg_bytes(blank=True), "image/jpeg")}, data={"scenario": "local_tax"})
    events = parse_sse((await client.get(f"/api/analyze/{r.json()['sessionId']}/events")).text)
    assert events[-1][0] == "result"  # 점검을 끄면 그대로 모델로 간다
    get_settings.cache_clear()
