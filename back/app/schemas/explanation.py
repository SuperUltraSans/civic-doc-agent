"""쉬운 말 설명 — 프론트 구현지시서 5.2절."""

from __future__ import annotations

from typing import Literal

from app.schemas.base import ApiModel


class Term(ApiModel):
    term: str
    plain: str
    source: Literal["dictionary", "llm"]


class Explanation(ApiModel):
    level: Literal[1, 2]
    summary_template: str
    consequences: list[str]
    terms: list[Term]
