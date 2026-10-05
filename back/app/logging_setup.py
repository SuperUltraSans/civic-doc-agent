"""JSON 한 줄 로그 (지시서 10장).

필드: sessionId, node, status, durationMs, tokensIn, tokensOut, detail(가림 처리 후).
전화번호·계좌·주소·문서 원문 발췌는 남기지 않거나 가린다 (지시서 8장).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from app.timeutil import now_iso

logger = logging.getLogger("ilgeo")

# 숫자 8자리 이상이 하이픈·공백·점으로 이어진 덩어리 → 전화번호·계좌번호로 보고 가린다.
_NUMBER_RUN = re.compile(r"(?<![\d])(?:\+?\d[\d\- .]{6,}\d)(?![\d])")
_URL = re.compile(r"(?i)\b(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?")


def mask_number(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if len(digits) < 8:
        return text
    head = digits[:3] if digits.startswith("0") and len(digits) >= 10 else ""
    tail = digits[-4:]
    if head:
        return f"{head}-****-{tail}"
    return f"****-{tail}"


def mask_sensitive(text: str | None) -> str | None:
    """로그용 가림 처리: 긴 숫자열(전화·계좌)은 끝 4자리만, 주소(URL)는 경로를 지운다."""
    if not text:
        return text
    masked = _NUMBER_RUN.sub(lambda m: mask_number(m.group(0)), text)

    def _strip_path(m: re.Match[str]) -> str:
        raw = m.group(0)
        host = re.sub(r"(?i)^https?://", "", raw).split("/", 1)[0]
        return f"{host}/…" if "/" in raw.split("://", 1)[-1] else host

    return _URL.sub(_strip_path, masked)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": now_iso(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            # 예외 메시지에는 문서 내용이 들어갈 수 있어 형식명만 남긴다.
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers[:] = [handler]
    logger.setLevel(level.upper())
    logger.propagate = False


def log_event(msg: str, *, level: int = logging.INFO, exc_info: bool = False, **fields: Any) -> None:
    clean: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        clean[key] = mask_sensitive(value) if isinstance(value, str) else value
    logger.log(level, msg, extra={"fields": clean}, exc_info=exc_info)
