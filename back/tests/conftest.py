"""테스트 공통 설정: LLM_PROVIDER=fake, 임시 SQLite, 빠른 scripted 재생."""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="ilgeo-test-"))
os.environ.update(
    {
        "LLM_PROVIDER": "fake",
        "AGENT_MODE": "live",
        "SCRIPTED_SPEED": "fast",
        "LOG_LEVEL": "WARNING",
        "DB_PATH": str(_TMP / "test.db"),
        "RATE_LIMIT_PER_MINUTE": "0",
        "DATA_GO_KR_SERVICE_KEY": "",
        "NAVER_CLIENT_ID": "",
        "NAVER_CLIENT_SECRET": "",
    }
)

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.llm.client import reset_llm  # noqa: E402


def jpeg_bytes(size: tuple[int, int] = (800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def set_mode(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    def _set(mode: str) -> None:
        monkeypatch.setenv("AGENT_MODE", mode)
        get_settings.cache_clear()
        reset_llm()

    yield _set
    monkeypatch.setenv("AGENT_MODE", "live")
    get_settings.cache_clear()
    reset_llm()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c


def parse_sse(text: str) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    name, data = None, None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
        elif line == "" and name is not None:
            events.append((name, data))
            name, data = None, None
    return events


async def run_session(
    client: httpx.AsyncClient,
    scenario: str,
    *,
    answer: str | None = "김해시",
    profile: dict[str, Any] | None = None,
) -> list[tuple[str, Any]]:
    """POST /analyze → (필요하면 POST /answer) → GET /events 전체를 파싱해 돌려준다."""
    from app.sessions.manager import get_manager

    data: dict[str, str] = {"scenario": scenario}
    if profile is not None:
        data["profile"] = json.dumps(profile)
    r = await client.post("/api/analyze", files={"image": ("doc.jpg", jpeg_bytes(), "image/jpeg")}, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"sessionId"}
    sid = body["sessionId"]
    session = get_manager().sessions[sid]
    for _ in range(1000):
        if session.pending_question or session.finished:
            break
        await asyncio.sleep(0.01)
    if session.pending_question:
        r = await client.post(f"/api/analyze/{sid}/answer", json={"field": "region", "value": answer})
        assert r.status_code == 204
    r = await client.get(f"/api/analyze/{sid}/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)
