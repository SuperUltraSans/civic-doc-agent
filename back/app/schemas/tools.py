"""도구 결과 — 프론트 구현지시서 5.4절."""

from __future__ import annotations

from typing import Literal

from app.schemas.base import ApiModel


class ImpersonationResult(ApiModel):
    status: Literal["match", "mismatch", "unknown"]
    checked_value: str
    official_phone: str | None = None
    official_source: str | None = None
    red_flags: list[str]


class DeadlineResult(ApiModel):
    due_date: str
    amount: int | None = None
    calendar_title: str


class WelfareItem(ApiModel):
    name: str
    summary: str
    reason: str
    url: str


class WelfareResult(ApiModel):
    items: list[WelfareItem]
    used_profile: bool
    fallback_used: bool
