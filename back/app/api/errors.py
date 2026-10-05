"""사용자에게 그대로 보여줄 수 있는 오류 응답 ({ code, message }). 내부 예외 메시지를 넣지 않는다."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.logging_setup import log_event


class ApiException(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


UNSUPPORTED_IMAGE = "이 사진은 열 수 없어요. 카메라로 다시 찍어 주세요"
SESSION_GONE = "처음부터 다시 해 주세요"
RESULT_GONE = "시간이 지나서 다시 설명할 수 없어요. 문서를 다시 찍어 주세요"
SERVER_ERROR = "문제가 생겼어요. 다시 해 볼까요?"


async def api_exception_handler(_: Request, exc: ApiException) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    log_event("request validation failed", level=30, path=request.url.path, errors=len(exc.errors()))
    return JSONResponse(status_code=422, content={"code": "server", "message": SERVER_ERROR})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log_event("unhandled error", level=40, path=request.url.path, exc_info=True)
    return JSONResponse(status_code=500, content={"code": "server", "message": SERVER_ERROR})
