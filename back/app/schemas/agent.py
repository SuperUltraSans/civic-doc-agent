"""에이전트 단계·계획·진행 중 이벤트 — 프론트 구현지시서 5.3절, 5.7절."""

from __future__ import annotations

from typing import Literal

from app.schemas.base import ApiModel

StepStatus = Literal["pending", "running", "done", "skipped", "failed"]
ToolName = Literal["check_impersonation", "manage_deadline", "search_welfare", "lookup_terms"]
TOOL_NAMES: tuple[str, ...] = ("check_impersonation", "manage_deadline", "search_welfare", "lookup_terms")
# 플래너가 고를 수 있는 도구 (lookup_terms는 explain 노드가 직접 호출)
PLANNABLE_TOOLS: tuple[str, ...] = ("check_impersonation", "manage_deadline", "search_welfare")


class AgentStep(ApiModel):
    id: str
    label: str
    done_label: str | None = None
    status: StepStatus
    tool: ToolName | None = None
    detail: str | None = None


class PlanItem(ApiModel):
    tool: ToolName
    reason: str
    required: bool


class UserProfile(ApiModel):
    region: str | None = None  # 시·군·구 이름만
    age_group: Literal["60s", "70s", "80plus"] | None = None


class InfoOption(ApiModel):
    label: str
    value: str


class InfoQuestion(ApiModel):
    field: Literal["region", "ageGroup"]
    question: str
    options: list[InfoOption]


class RetakeRequest(ApiModel):
    message: str
    tips: list[str]


class ApiError(ApiModel):
    code: Literal["network", "timeout", "server", "unsupported_image"]
    message: str


class AnswerRequest(ApiModel):
    field: Literal["region", "ageGroup"]
    value: str | None = None


class AnalyzeStarted(ApiModel):
    session_id: str
