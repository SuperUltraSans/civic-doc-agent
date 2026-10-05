"""LLM 구조화 출력 스키마 (노드별).

주의: Bedrock·Anthropic 구조화 출력은 숫자 범위·길이 제약 같은 키워드를 지원하지 않거나 무시한다.
여기서는 모양만 정하고, 값 검사는 코드(validate, verify_explanation 등)가 한다.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.base import ApiModel

LlmDocType = Literal[
    "health_insurance_bill",
    "local_tax_bill",
    "fine_notice",
    "basic_pension_notice",
    "suspicious_message",
    "unknown",
]


class ExtractFieldsOut(ApiModel):
    amount: int | None = None
    due_date: str | None = None
    billing_month: str | None = None
    arrears: int | None = None
    phone: str | None = None
    url: str | None = None


class ExtractConfidenceOut(ApiModel):
    amount: float | None = None
    due_date: float | None = None
    billing_month: float | None = None
    arrears: float | None = None
    phone: float | None = None
    url: float | None = None


class ExtractOut(ApiModel):
    """문서 종류 분류 + 필드 추출 (한 번의 VLM 호출)."""

    doc_type: LlmDocType
    issuer: str | None = None
    fields: ExtractFieldsOut
    confidence: ExtractConfidenceOut
    legible: bool
    raw_text_excerpt: str | None = None


class RecheckOut(ApiModel):
    """의심 필드만 다시 읽는 집중 재추출."""

    fields: ExtractFieldsOut
    confidence: ExtractConfidenceOut


class ExplainTermOut(ApiModel):
    term: str
    plain: str


class ExplainOut(ApiModel):
    summary_template: str
    consequences: list[str]
    terms: list[ExplainTermOut]


class PlanStepOut(ApiModel):
    tool: str
    reason: str


class PlanOut(ApiModel):
    situation: str
    plan: list[PlanStepOut]
    need_user_info: list[str]


class WelfarePickOut(ApiModel):
    id: str
    reason: str


class WelfareRerankOut(ApiModel):
    items: list[WelfarePickOut]


class ScamPickOut(ApiModel):
    id: str
    evidence: str


class ScamSelectOut(ApiModel):
    selected: list[ScamPickOut]
