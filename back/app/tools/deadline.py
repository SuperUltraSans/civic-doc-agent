"""manage_deadline — 순수 코드 (지시서 5.7절 (2)). 달력 파일(.ics)은 프론트가 만든다."""

from __future__ import annotations

from typing import Any

from app.schemas.document import DOC_TYPE_LABELS, PAYMENT_NAMES
from app.schemas.tools import DeadlineResult


def calendar_title(doc_type: str) -> str:
    if doc_type in PAYMENT_NAMES:
        return f"{PAYMENT_NAMES[doc_type]} 내는 날 (읽어드림)"
    if doc_type == "basic_pension_notice":
        return "기초연금 안내 기한 (읽어드림)"
    return f"{DOC_TYPE_LABELS.get(doc_type, '문서')} 기한 (읽어드림)"


def manage_deadline(document: dict[str, Any]) -> dict[str, Any]:
    fields = document.get("fields") or {}
    due = fields.get("dueDate")
    if not due:
        raise ValueError("dueDate 없음")
    return DeadlineResult(
        due_date=due,
        amount=fields.get("amount"),
        calendar_title=calendar_title(document.get("docType", "unknown")),
    ).to_api()
