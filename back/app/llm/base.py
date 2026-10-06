"""LLM 공급자 공통: 오류, 토큰 사용량, 역할별 호출 대상, 공급자 클라이언트 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

Role = Literal["vision", "reason", "fast"]
ROLES: tuple[Role, ...] = ("vision", "reason", "fast")
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """LLM 호출 실패의 기반 클래스. 메시지는 내부용이며 사용자에게 보내지 않는다."""


class LLMTimeout(LLMError):
    pass


class LLMNetworkError(LLMError):
    pass


class LLMOutputError(LLMError):
    pass


class LLMConfigError(LLMError):
    pass


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0

    def add(self, other: "Usage") -> None:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out


@dataclass(frozen=True)
class Target:
    """한 역할의 호출 대상: 어느 공급자의 어느 모델을 어떤 사고 수준(effort)으로 부를지."""

    role: Role
    provider: str  # openai | google | anthropic | fake
    model: str
    effort: str = ""  # 비우면 공급자 기본값


class ProviderClient(ABC):
    """공급자 하나의 구조화 출력 호출. 재시도·시간 제한·로그는 LLMRouter 가 맡는다."""

    name: str = "base"

    @abstractmethod
    async def call(
        self,
        *,
        target: Target,
        node: str,
        system: str,
        user: str,
        schema: type[T],
        image: bytes | None,
        timeout: float,
        deterministic: bool,
    ) -> tuple[T, Usage]: ...
