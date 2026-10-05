"""문서와 추출 결과 — 프론트 구현지시서 5.1절과 1:1 대응."""

from __future__ import annotations

from typing import Literal

from app.schemas.base import ApiModel

DocType = Literal[
    "health_insurance_bill",  # 건강보험료 고지서
    "local_tax_bill",  # 지방세 고지서
    "fine_notice",  # 과태료 고지서
    "basic_pension_notice",  # 기초연금 안내문
    "suspicious_message",  # 사칭 의심 문자
    "unknown",
]

DOC_TYPES: tuple[str, ...] = (
    "health_insurance_bill",
    "local_tax_bill",
    "fine_notice",
    "basic_pension_notice",
    "suspicious_message",
    "unknown",
)

# 화면 표시용 이름은 LLM이 아니라 코드가 정한다.
DOC_TYPE_LABELS: dict[str, str] = {
    "health_insurance_bill": "건강보험료 고지서",
    "local_tax_bill": "지방세 고지서",
    "fine_notice": "과태료 고지서",
    "basic_pension_notice": "기초연금 안내문",
    "suspicious_message": "사칭 의심 문자",
    "unknown": "알 수 없는 문서",
}

BILL_TYPES: frozenset[str] = frozenset({"health_insurance_bill", "local_tax_bill", "fine_notice"})

# 고지서별 "무엇을 내는지" 이름 (할 일 제목·달력 제목에 사용)
PAYMENT_NAMES: dict[str, str] = {
    "health_insurance_bill": "건강보험료",
    "local_tax_bill": "지방세",
    "fine_notice": "과태료",
}

FIELD_NAMES: tuple[str, ...] = ("amount", "dueDate", "billingMonth", "arrears", "phone", "url")


class ExtractedFields(ApiModel):
    amount: int | None = None  # 원 단위 정수
    due_date: str | None = None  # 'YYYY-MM-DD'
    billing_month: str | None = None  # 'YYYY-MM'
    arrears: int | None = None  # 체납액
    phone: str | None = None  # 문서에 적힌 연락처
    url: str | None = None  # 문서에 적힌 주소


class ExtractedDocument(ApiModel):
    doc_type: DocType
    doc_type_label: str
    issuer: str
    fields: ExtractedFields
