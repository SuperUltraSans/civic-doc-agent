"""할 일과 최종 결과 — 프론트 구현지시서 5.5절, 5.6절."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from app.schemas.agent import AgentStep, PlanItem
from app.schemas.base import ApiModel
from app.schemas.document import ExtractedDocument
from app.schemas.explanation import Explanation
from app.schemas.tools import DeadlineResult, ImpersonationResult, WelfareResult


class CallAction(ApiModel):
    type: Literal["call"] = "call"
    label: str
    tel: str


class LinkAction(ApiModel):
    type: Literal["link"] = "link"
    label: str
    url: str


class CalendarAction(ApiModel):
    type: Literal["calendar"] = "calendar"
    label: str
    title: str
    date: str


TodoAction = Annotated[Union[CallAction, LinkAction, CalendarAction], Field(discriminator="type")]


class ResultTodo(ApiModel):
    """TodoItem에서 status·createdAt·doneAt을 뺀 모양 (프론트가 채운다)."""

    id: str
    doc_id: str
    title: str
    amount: int | None = None
    due_date: str | None = None
    actions: list[TodoAction]


class ToolResults(ApiModel):
    impersonation: ImpersonationResult | None = None
    deadline: DeadlineResult | None = None
    welfare: WelfareResult | None = None


class AnalysisResult(ApiModel):
    doc_id: str
    document: ExtractedDocument
    explanation: Explanation
    plan: list[PlanItem]
    tools: ToolResults
    todos: list[ResultTodo]
    steps: list[AgentStep]
    created_at: str


class SimplifyRequest(ApiModel):
    doc_id: str
