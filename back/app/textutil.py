"""한국어 문장 조립 도우미 (조사 선택 등)."""

from __future__ import annotations

import re


def has_final_consonant(word: str) -> bool:
    """마지막 글자에 받침이 있는지. 한글이 아니면 받침 없음으로 본다."""
    for ch in reversed(word.strip()):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return (code - 0xAC00) % 28 != 0
        if ch.isdigit():
            # 숫자 읽기: 0(영),1(일),3(삼),6(육),7(칠),8(팔) → 받침 있음
            return ch in "013678"
        if ch.isalpha():
            return False
    return False


def ieyo(word: str) -> str:
    """'고지서예요' / '안내문이에요'."""
    return f"{word}{'이에요' if has_final_consonant(word) else '예요'}"


def eul_reul(word: str) -> str:
    return f"{word}{'을' if has_final_consonant(word) else '를'}"


def i_ga(word: str) -> str:
    return f"{word}{'이' if has_final_consonant(word) else '가'}"


# 단정 표현 금지 (지시서 0장 4, 13장). LLM이 쓴 문장에 섞이면 그 문장을 쓰지 않는다.
ASSERTIVE_PHRASES: tuple[str, ...] = (
    "안전합니다",
    "안전해요",
    "안전한 문서",
    "안전한 문자",
    "정상입니다",
    "정상이에요",
    "받을 수 있습니다",
    "받으실 수 있습니다",
    "대상입니다",
    "대상이에요",
    "확실합니다",
    "확실해요",
    "틀림없",
)


def is_assertive(text: str) -> bool:
    return any(p in text for p in ASSERTIVE_PHRASES)


# 숫자·날짜는 LLM이 문장에 쓰지 않는다 (지시서 0장 3). 문장 안의 값 노출을 찾는 규칙.
NUMBER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\d{3,}"), "3자리 이상 숫자"),
    (re.compile(r"\d+\s*[./\-]\s*\d+"), "날짜·숫자 형태"),
    (re.compile(r"\d+\s*(?:년|월|일|원|만|천|억|%|퍼센트|시|분)"), "날짜·금액 표현"),
    (re.compile(r"\d{1,3}(?:,\d{3})+"), "쉼표 숫자"),
)


def numeric_issue(text: str) -> str | None:
    """문장에 금액·날짜·번호 같은 숫자 표현이 있으면 그 종류, 없으면 None."""
    for pattern, why in NUMBER_PATTERNS:
        if pattern.search(text):
            return why
    return None
