"""그래프 상태 정의 (지시서 4.3절).

상태 값은 체크포인터가 직렬화하므로 Pydantic 모델이 아니라 dict(camelCase, 프론트 계약 모양)로 둔다.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    scenario: str | None
    image_bytes: bytes | None  # preprocess 후 extract(재추출 포함)가 끝나면 즉시 None
    profile: dict[str, Any]  # UserProfile (프론트가 매 요청에 보냄, 서버에 저장하지 않음)

    # extract / validate (Goal, Feedback)
    document: dict[str, Any]  # ExtractedDocument
    field_confidence: dict[str, float | None]
    legible: bool
    raw_excerpt: str | None  # 검증·수법 검색용 발췌. 결과·로그에 남기지 않음
    extract_attempts: int
    recheck_fields: list[str] | None
    recheck_blind: list[str] | None  # 앞서 읽은 값을 보여 주지 않고 다시 읽을 필드 (기간 밖 기한)
    recheck_previous: dict[str, Any] | None  # 그 필드의 첫 판독값 (두 번 같으면 인정)
    validate_notes: list[str]
    retake: dict[str, Any] | None  # RetakeRequest

    # explain / verify_explanation (Goal, Feedback)
    explanation: dict[str, Any]  # Explanation
    explain_attempts: int
    explain_violations: list[str] | None
    explain_notes: list[str]

    # plan / ask_user (Planning, Reasoning, Memory)
    situation: str
    plan: list[dict[str, Any]]  # PlanItem[]
    need_info: dict[str, Any] | None
    asked: bool

    # run_tools / evaluate (Tool Use, Feedback)
    tool_results: dict[str, Any]
    failed_tools: list[str]
    pending_tools: list[str] | None
    welfare_ignore_region: bool
    eval_attempts: int
    eval_notes: list[str]

    # review / run_followups (Reasoning, Tool Use) — 도구 결과를 보고 고른 추가 도구 (1회)
    reviewed: bool
    followups: list[dict[str, Any]] | None

    # 실행 로그 — 병렬 노드가 함께 쓰므로 이어 붙이는 리듀서를 쓴다
    steps: Annotated[list[dict[str, Any]], operator.add]

    # compose
    result: dict[str, Any]  # AnalysisResult
