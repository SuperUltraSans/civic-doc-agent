"""validate — 형식·논리 검사 · Feedback (지시서 5.3절).

코드로 검사한다. LLM에 맡기지 않는다.
1. 형식 오류·의심 필드가 있으면 그 필드만 다시 묻는 집중 프롬프트로 1회 재추출.
2. 재추출 후에도 문제가 있는 선택 필드는 null로 버린다 (틀린 값보다 빼는 것이 낫다).
3. 필수 필드가 없거나 legible=false 이거나 docType=unknown 이면 need_retake 로 끝낸다.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

from app.agent.events import StepHandle
from app.agent.state import AgentState
from app.schemas.document import BILL_TYPES
from app.timeutil import today
from app.tools.impersonation import is_valid_phone

AMOUNT_LIMIT = 100_000_000  # 1억 원 미만
CONFIDENCE_MIN = 0.7
DATE_PAST_DAYS = 365
DATE_FUTURE_DAYS = 180

LABEL = "금액과 날짜를 확인하고 있어요"
DONE_LABEL = "금액과 날짜를 다시 확인했어요"

TIPS_BLURRY = ["밝은 곳에서 찍어 주세요", "종이를 평평하게 펴 주세요", "종이 전체가 보이게 찍어 주세요"]
TIPS_UNKNOWN = ["종이 전체가 보이게 찍어 주세요", "밝은 곳에서 찍어 주세요"]
TIPS_MISSING = ["종이 전체가 보이게 찍어 주세요", "밝은 곳에서 찍어 주세요", "종이를 평평하게 펴 주세요"]


# ── 필드별 규칙 ──
def parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_month(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        return None
    year, month = int(value[:4]), int(value[5:])
    return (year, month) if 1 <= month <= 12 else None


def is_valid_amount(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < AMOUNT_LIMIT


def is_valid_due_date(value: Any, base: date) -> bool:
    d = parse_date(value)
    return d is not None and base - timedelta(days=DATE_PAST_DAYS) <= d <= base + timedelta(days=DATE_FUTURE_DAYS)


def is_valid_billing_month(value: Any, due_date: Any) -> bool:
    month = parse_month(value)
    if month is None:
        return False
    due = parse_date(due_date)
    return due is None or month <= (due.year, due.month)


def is_valid_arrears(value: Any, amount: Any) -> bool:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= AMOUNT_LIMIT:
        return False
    return not isinstance(amount, int) or value <= amount


def is_valid_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or " " in value.strip():
        return False
    raw = value.strip()
    try:
        parts = urlsplit(raw if "://" in raw else f"http://{raw}")
    except ValueError:
        return False
    host = parts.hostname or ""
    return "." in host and bool(re.fullmatch(r"[a-z0-9.-]+", host))


OUT_OF_RANGE = "기간 밖"


def field_problems(fields: dict[str, Any], confidence: dict[str, Any], base: date) -> dict[str, str]:
    """필드 이름 → 문제 설명. 값이 없는 필드는 검사하지 않는다.

    기한이 날짜 형식은 맞는데 오늘 기준 −365일 ~ +180일을 벗어나면 '형식 오류'가 아니라 '기간 밖'이다.
    연도를 잘못 읽었을 수도 있지만, 오래된 문서일 수도 있어서 다르게 다룬다 (validate 참고).
    """
    problems: dict[str, str] = {}
    due = fields.get("dueDate")
    if due is not None and parse_date(due) is not None and not is_valid_due_date(due, base):
        problems["dueDate"] = OUT_OF_RANGE
    checks = {
        "amount": lambda v: is_valid_amount(v),
        "dueDate": lambda v: parse_date(v) is not None,
        "billingMonth": lambda v: is_valid_billing_month(v, fields.get("dueDate")),
        "arrears": lambda v: is_valid_arrears(v, fields.get("amount")),
        "phone": lambda v: is_valid_phone(v),
        "url": lambda v: is_valid_url(v),
    }
    for name, check in checks.items():
        value = fields.get(name)
        if value is None or name in problems:
            continue
        if not check(value):
            problems[name] = "형식 오류"
            continue
        conf = confidence.get(name)
        if isinstance(conf, (int, float)) and conf < CONFIDENCE_MIN:
            problems[name] = f"신뢰도 낮음({conf:.2f})"
    return problems


def required_fields(doc_type: str) -> list[str]:
    if doc_type in BILL_TYPES:
        return ["amount", "dueDate"]
    return []


def missing_required(doc_type: str, fields: dict[str, Any]) -> list[str]:
    if doc_type == "suspicious_message":
        return [] if (fields.get("phone") or fields.get("url")) else ["phone", "url"]
    return [name for name in required_fields(doc_type) if fields.get(name) is None]


TIP_DATE = "날짜가 적힌 부분이 잘 보이게 찍어 주세요"


def retake_request(kind: str, missing: list[str] | None = None) -> dict[str, Any]:
    if kind == "unknown":
        return {"message": "어떤 문서인지 알아보기 어려워요", "tips": TIPS_UNKNOWN}
    if kind == "missing":
        tips = ([TIP_DATE] if "dueDate" in (missing or []) else []) + TIPS_MISSING
        return {"message": "글씨가 잘 안 보여요", "tips": tips[:3]}
    return {"message": "글씨가 잘 안 보여요", "tips": TIPS_BLURRY}


# ── 노드 ──
async def validate(state: AgentState) -> dict[str, Any]:
    document = dict(state["document"])
    fields = dict(document.get("fields") or {})
    confidence = dict(state.get("field_confidence") or {})
    doc_type = document.get("docType", "unknown")
    attempts = state.get("extract_attempts", 1)
    notes = list(state.get("validate_notes") or [])
    step = StepHandle(session_id=state.get("session_id"), id="validate", label=LABEL, done_label=DONE_LABEL, node="validate")

    def end_retake(kind: str, note: str, missing: list[str] | None = None) -> dict[str, Any]:
        notes.append(note)
        final = step.finish("failed", " | ".join(notes) + " → 다시 찍기 안내")
        return {"retake": retake_request(kind, missing), "image_bytes": None, "validate_notes": notes, "steps": [final]}

    if not state.get("legible", True):
        return end_retake("blurry", "legible=false")
    if doc_type == "unknown":
        return end_retake("unknown", "docType=unknown")

    problems = field_problems(fields, confidence, today())
    missing = missing_required(doc_type, fields)

    if (problems or missing) and attempts < 2:
        targets = sorted(set(problems) | set(missing))
        notes.append(", ".join(f"{name} 재확인({problems.get(name, '누락')})" for name in targets))
        step.running(detail=notes[-1])
        blind = [n for n, why in problems.items() if why == OUT_OF_RANGE]
        return {
            "recheck_fields": targets,
            "recheck_blind": blind,  # 앞서 읽은 값을 보여 주지 않고 다시 읽게 할 필드
            "recheck_previous": {n: fields.get(n) for n in blind},
            "validate_notes": notes,
        }

    # 재추출 이후(또는 문제 없음): 남은 문제를 정리한다
    previous = state.get("recheck_previous") or {}
    for name, why in list(problems.items()):
        if why == OUT_OF_RANGE and name in previous and previous[name] == fields.get(name):
            # 앞서 읽은 값을 보여 주지 않고 다시 읽었는데 같은 날짜 → 잘못 읽은 것이 아니라 오래된(또는 먼) 문서로 본다.
            # 화면은 '며칠 지났어요'로 알려 준다. 사진을 다시 찍어도 같은 결과라 다시 찍기로 돌려보내지 않는다.
            del problems[name]
            notes.append(f"{name} 기간 밖이지만 두 번 같은 값으로 읽음 → 유지(오래된 문서)")
        elif why == OUT_OF_RANGE:
            problems[name] = "형식 오류"  # 두 번 읽은 값이 다르면 믿을 수 없다 → 아래에서 버린다
    required = set(required_fields(doc_type))
    dropped = []
    for name, why in problems.items():
        if name in required and why == "형식 오류":
            fields.pop(name, None)  # 필수 필드 형식 오류 → 아래 누락 검사에서 다시 찍기
        elif name not in required:
            fields.pop(name, None)  # 문제가 남은 선택 필드는 버린다
            dropped.append(name)
    if dropped:
        notes.append(f"{','.join(dropped)} 버림(재확인 후에도 문제)")
    low_required = [n for n, why in problems.items() if n in required and why != "형식 오류"]
    if low_required:
        notes.append(f"{','.join(low_required)} 신뢰도 낮지만 형식은 맞아 유지")

    missing = missing_required(doc_type, fields)
    if missing:
        return end_retake("missing", f"필수 값 누락: {','.join(missing)}", missing)

    document["fields"] = fields
    if attempts < 2 and not notes:
        step.running()
    if not notes:
        notes.append("형식·범위·신뢰도 검사 통과")
    elif attempts >= 2:
        notes.append("재확인 완료")
    final = step.finish("done", " | ".join(notes))
    return {"document": document, "image_bytes": None, "validate_notes": notes, "steps": [final]}


def route_after_validate(state: AgentState) -> str | list[str]:
    from langgraph.graph import END

    if state.get("retake"):
        return END
    if state.get("recheck_fields"):
        return "extract"
    return ["explain", "plan"]
