"""세션 생성, 이벤트 버퍼, 사용자 응답 대기, 만료 정리 (지시서 3.3, 3.4절).

- POST /api/analyze 를 받으면 세션을 만들고 바로 그래프 실행을 시작한다.
- 이벤트는 세션 버퍼에 쌓이고, GET /events 가 연결되면 버퍼부터 모두 보낸 뒤 이어서 보낸다.
- 세션은 종료 이벤트 후 2분, 또는 생성 후 10분이 지나면 지운다.
- /api/simplify 용으로 추출 결과·설명만 30분 보관한다 (연락처·주소 제거, 이미지 없음).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.logging_setup import log_event

TERMINAL_EVENTS = frozenset({"need_retake", "result", "error"})


class TooBusyError(Exception):
    """동시 처리 세션 수 상한 초과."""


@dataclass
class SessionEvent:
    name: str
    data: Any

    def to_sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.name}\ndata: {payload}\n\n"


@dataclass
class Session:
    id: str
    profile: dict[str, Any]
    scenario: str | None
    created_at: float = field(default_factory=time.monotonic)
    events: list[SessionEvent] = field(default_factory=list)
    finished_at: float | None = None
    pending_question: dict[str, Any] | None = None
    task: asyncio.Task[Any] | None = None
    _changed: asyncio.Event = field(default_factory=asyncio.Event)
    _answer: asyncio.Future[str | None] | None = None
    _loop: asyncio.AbstractEventLoop | None = None
    _image: bytes | None = None

    # ── 이미지: 메모리에서만, 한 번 꺼내면 세션에서 지운다 ──
    def put_image(self, data: bytes) -> None:
        self._image = data

    def take_image(self) -> bytes | None:
        data, self._image = self._image, None
        return data

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    # ── 이벤트 ──
    def push(self, name: str, data: Any) -> None:
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            # 다른 스레드(예: 동기 LLM 호출 스레드)에서 온 이벤트는 이벤트 루프로 넘긴다.
            loop.call_soon_threadsafe(self._push, name, data)
            return
        self._push(name, data)

    def _push(self, name: str, data: Any) -> None:
        if self.finished:
            return  # 종료 후 이벤트는 버린다
        self.events.append(SessionEvent(name, data))
        if name in TERMINAL_EVENTS:
            self.finished_at = time.monotonic()
            self.pending_question = None
        old, self._changed = self._changed, asyncio.Event()
        old.set()

    def finish(self, name: str, data: Any) -> None:
        assert name in TERMINAL_EVENTS
        self.push(name, data)

    async def stream(self, ping_seconds: float) -> AsyncIterator[str]:
        """버퍼의 이벤트를 처음부터 보내고, 이후 이벤트를 이어서 보낸다. 종료 이벤트 후 닫는다."""
        idx = 0
        yield ": connected\n\n"
        while True:
            changed = self._changed
            while idx < len(self.events):
                event = self.events[idx]
                idx += 1
                yield event.to_sse()
                if event.name in TERMINAL_EVENTS:
                    return
            try:
                await asyncio.wait_for(changed.wait(), timeout=ping_seconds)
            except TimeoutError:
                yield ": ping\n\n"

    # ── 사용자 응답 대기 (질문은 세션당 최대 1회) ──
    def ask(self, question: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        self._answer = loop.create_future()
        self.pending_question = question
        self.push("need_info", question)

    def submit_answer(self, field_name: str, value: str | None) -> bool:
        q = self.pending_question
        if q is None or self._answer is None or self._answer.done() or q.get("field") != field_name:
            return False
        self._answer.set_result(value)
        self.pending_question = None
        return True

    async def wait_answer(self, timeout: float) -> str | None:
        """응답이 없으면 timeout 뒤 None(건너뛰기)으로 처리한다."""
        assert self._answer is not None
        try:
            return await asyncio.wait_for(asyncio.shield(self._answer), timeout=timeout)
        except TimeoutError:
            self.pending_question = None
            log_event("answer timeout → 건너뛰기로 처리", sessionId=self.id, node="ask_user", status="skipped")
            return None


@dataclass
class StoredResult:
    """/api/simplify 용 보관본. 추출 결과(연락처·주소 제거)와 설명만."""

    doc_id: str
    document: dict[str, Any]
    explanation: dict[str, Any]
    expires_at: float
    scripted_level2: dict[str, Any] | None = None


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.results: dict[str, StoredResult] = {}
        self._sweeper: asyncio.Task[None] | None = None
        self._rate: dict[str, deque[float]] = {}

    # ── 세션 ──
    def active_count(self) -> int:
        return sum(1 for s in self.sessions.values() if not s.finished)

    def create(
        self,
        *,
        image: bytes,
        profile: dict[str, Any],
        scenario: str | None,
        runner: Callable[[Session], Awaitable[None]],
    ) -> Session:
        settings = get_settings()
        if self.active_count() >= settings.max_concurrent_sessions:
            raise TooBusyError
        session = Session(id=uuid.uuid4().hex, profile=profile, scenario=scenario)
        session._loop = asyncio.get_running_loop()
        session.put_image(image)
        self.sessions[session.id] = session
        session.task = asyncio.create_task(self._run(session, runner), name=f"session-{session.id}")
        return session

    async def _run(self, session: Session, runner: Callable[[Session], Awaitable[None]]) -> None:
        try:
            await runner(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            log_event("session runner crashed", level=40, exc_info=True, sessionId=session.id)
            session.finish("error", {"code": "server", "message": "문제가 생겼어요. 다시 해 볼까요?"})
        finally:
            session.take_image()  # 어떤 경우에도 이미지를 남기지 않는다
            if not session.finished:
                session.finish("error", {"code": "server", "message": "문제가 생겼어요. 다시 해 볼까요?"})

    def get(self, session_id: str) -> Session | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        if self._expired(session, time.monotonic()):
            self._drop(session_id)
            return None
        return session

    def _expired(self, session: Session, now: float) -> bool:
        s = get_settings()
        if now - session.created_at > s.session_ttl_seconds:
            return True
        return session.finished_at is not None and now - session.finished_at > s.session_linger_seconds

    def _drop(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        session.take_image()
        if session.task and not session.task.done():
            session.task.cancel()

    # ── 결과 보관 (/api/simplify) ──
    def store_result(
        self,
        doc_id: str,
        document: dict[str, Any],
        explanation: dict[str, Any],
        scripted_level2: dict[str, Any] | None = None,
    ) -> None:
        doc = json.loads(json.dumps(document))
        fields = doc.get("fields") or {}
        fields.pop("phone", None)  # 연락처·주소는 보관하지 않는다
        fields.pop("url", None)
        self.results[doc_id] = StoredResult(
            doc_id=doc_id,
            document=doc,
            explanation=explanation,
            expires_at=time.monotonic() + get_settings().result_ttl_seconds,
            scripted_level2=scripted_level2,
        )

    def get_result(self, doc_id: str) -> StoredResult | None:
        stored = self.results.get(doc_id)
        if stored is None:
            return None
        if time.monotonic() > stored.expires_at:
            self.results.pop(doc_id, None)
            return None
        return stored

    # ── 요청 수 제한 (IP별, 1분 창) ──
    def allow_request(self, key: str) -> bool:
        limit = get_settings().rate_limit_per_minute
        if limit <= 0:
            return True
        now = time.monotonic()
        window = self._rate.setdefault(key, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    # ── 만료 정리 ──
    def sweep(self) -> None:
        now = time.monotonic()
        for sid in [sid for sid, s in self.sessions.items() if self._expired(s, now)]:
            self._drop(sid)
        for doc_id in [d for d, r in self.results.items() if now > r.expires_at]:
            self.results.pop(doc_id, None)
        for key in [k for k, w in self._rate.items() if not w or now - w[-1] > 60]:
            self._rate.pop(key, None)

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            self.sweep()

    def start(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop(), name="session-sweeper")

    async def stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
        for sid in list(self.sessions):
            self._drop(sid)


manager = SessionManager()


def get_manager() -> SessionManager:
    return manager
