"""읽어드림 에이전트 API — FastAPI 앱, CORS, 라우터 등록."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser

from app.api import routes_analyze, routes_health, routes_simplify
from app.api.errors import (
    ApiException,
    api_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.config import get_settings
from app.llm.client import describe_targets
from app.logging_setup import log_event, setup_logging
from app.sessions.manager import get_manager
from app.store.db import init_db

# 업로드 이미지를 디스크 임시 파일로 넘기지 않고 메모리에만 두기 위해 (기본값 1MB → 11MB).
# 10MB를 넘는 업로드는 라우트에서 415로 거절한다.
MultiPartParser.spool_max_size = 11 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()
    manager = get_manager()
    manager.start()
    if settings.agent_mode == "live":
        # 형태소 분석기 로딩(수 초)을 첫 요청 전에 끝내 둔다
        from app.rag.retriever import get_retriever

        asyncio.get_running_loop().run_in_executor(None, get_retriever)
    log_event(
        "startup",
        appEnv=settings.app_env,
        agentMode=settings.agent_mode,
        llm=describe_targets(),  # 역할별 공급자·모델 (키는 남기지 않음)
    )
    yield
    await manager.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="읽어드림 에이전트 API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )
    app.add_exception_handler(ApiException, api_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(routes_health.router)
    app.include_router(routes_analyze.router)
    app.include_router(routes_simplify.router)
    return app


app = create_app()
