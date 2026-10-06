"""LLM 공급자 전환 — 지시서 7장.

역할마다 공급자·모델을 따로 고른다 (팀 결정, 2026-10-06):
| 역할 | 쓰는 노드 | 공급자 | 모델 (환경 변수) |
| vision | extract (문서 읽기) | google | MODEL_VISION = Gemini 3.8 Flash |
| reason | plan | openai | MODEL_REASON = GPT-6.1 Sol |
| fast | explain, 복지 재정렬, 수법 선택 | openai | MODEL_FAST = GPT-6 Luna |

- 공급자: 역할별 PROVIDER_VISION / PROVIDER_REASON / PROVIDER_FAST, 비우면 LLM_PROVIDER.
  LLM_PROVIDER=fake 이면 역할별 설정과 관계없이 모두 기록된 응답(테스트·초기 연동용)을 쓴다.
- 모델 ID는 코드에 쓰지 않고 환경 변수로 받는다. 어떤 역할의 모델이 비어 있으면 다른 역할의 (공급자, 모델)을 쓴다.
- AWS(Bedrock)는 쓰지 않기로 해서 공급자에서 뺐다.

그래프·노드 코드는 공급자를 모른다. 노드는 `get_llm().structured(...)` 하나만 쓴다.

호출 규칙 (지시서 7.3):
- 출력은 모두 구조화 출력 + Pydantic 검증. 검증 실패 시 1회 재시도.
- 시간 제한: extract 30초, 그 외 20초. 시간 초과·연결 실패는 1회 재시도.
- 노드별 소요 시간과 입력·출력 토큰 수를 로그에 남긴다.

temperature: 지시서는 추출·계획·판정 호출에 temperature 0을 요구한다. 그러나 OpenAI 추론 모델(GPT-5 이후)은
temperature 를 받지 않고, Gemini 3 계열은 기본값(1.0)에서 바꾸지 말라는 것이 공식 권고다. 그래서 받는(권고되는)
모델에만 0을 보내고, 나머지는 구조화 출력(JSON 스키마)과 코드 검사로 일관성을 확보한다.
"""

from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from app.config import get_settings
from app.llm.base import (
    ROLES,
    LLMConfigError,
    LLMError,
    LLMNetworkError,
    LLMOutputError,
    LLMTimeout,
    ProviderClient,
    Role,
    T,
    Target,
    Usage,
)
from app.logging_setup import log_event

__all__ = [
    "LLMConfigError",
    "LLMError",
    "LLMNetworkError",
    "LLMOutputError",
    "LLMRouter",
    "LLMTimeout",
    "Role",
    "Target",
    "Usage",
    "current_scenario",
    "current_session_id",
    "current_usage",
    "describe_line",
    "describe_targets",
    "get_llm",
    "load_prompt",
    "reset_llm",
    "resolve_target",
]

PROMPT_DIR = Path(__file__).parent / "prompts"
PROVIDERS = ("openai", "google", "anthropic")

# fake 공급자가 시나리오별 응답을 고를 때 쓴다 (세션 실행 시 설정).
current_scenario: ContextVar[str] = ContextVar("current_scenario", default="arrears")
# 단계(step)별 토큰 집계용. events.step_scope 가 설정한다.
current_usage: ContextVar["Usage | None"] = ContextVar("current_usage", default=None)
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)


@lru_cache
def load_prompt(name: str) -> str:
    """prompts/{name}.md 를 읽는다. 상단 버전 주석(<!-- -->)은 빼고 보낸다."""
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("<!--")]
    return "\n".join(lines).strip()


# ── 역할 → (공급자, 모델, 사고 수준) ──
def resolve_target(role: Role) -> Target:
    s = get_settings()
    if s.llm_provider == "fake":
        return Target(role=role, provider="fake", model="fake")
    configured = {
        "vision": (s.provider_vision or s.llm_provider, s.model_vision, s.effort_vision or s.llm_effort),
        "reason": (s.provider_reason or s.llm_provider, s.model_reason, s.effort_reason or s.llm_effort),
        "fast": (s.provider_fast or s.llm_provider, s.model_fast, s.effort_fast or s.llm_effort),
    }
    # 그 역할의 모델이 비어 있으면 다른 역할의 설정을 공급자와 함께 빌려 쓴다 (모델 ID만 섞이지 않게)
    for candidate in (role, *(r for r in ROLES if r != role)):
        provider, model, effort = configured[candidate]
        if model.strip():
            return Target(role=role, provider=provider, model=model.strip(), effort=effort.strip())
    raise LLMConfigError("모델 ID 환경 변수(MODEL_VISION / MODEL_REASON / MODEL_FAST)가 비어 있습니다")


def describe_targets() -> dict[str, dict[str, str]]:
    """역할별 (공급자, 모델, 사고 수준) — 시작 로그·평가 보고서용. 설정이 비어 있으면 그렇게 표시한다."""
    out: dict[str, dict[str, str]] = {}
    for role in ROLES:
        try:
            t = resolve_target(role)
            out[role] = {"provider": t.provider, "model": t.model, "effort": t.effort or "(기본값)"}
        except LLMConfigError:
            out[role] = {"provider": "(미지정)", "model": "(미지정)", "effort": ""}
    return out


def describe_line() -> str:
    """보고서 한 줄: 'vision google/gemini-3.8-flash · reason openai/gpt-6.1-sol · …'"""
    return " · ".join(f"{role} {t['provider']}/{t['model']}" + (f" (effort {t['effort']})" if t["effort"] else "") for role, t in describe_targets().items())


class FakeClient(ProviderClient):
    """테스트·초기 연동용. 시나리오별로 미리 기록한 응답을 돌려준다 (app/llm/fake.py)."""

    name = "fake"

    async def call(self, *, target, node, system, user, schema, image, timeout, deterministic):  # type: ignore[override]
        from app.llm.fake import fake_response

        await asyncio.sleep(0.01)
        data = fake_response(node=node, scenario=current_scenario.get(), user=user)
        return schema.model_validate(data), Usage(len(system) // 4 + len(user) // 4, 200)


def _make_client(provider: str) -> ProviderClient:
    if provider == "fake":
        return FakeClient()
    if provider == "openai":
        from app.llm.providers.openai_client import OpenAIClient

        return OpenAIClient()
    if provider == "google":
        from app.llm.providers.gemini_client import GeminiClient

        return GeminiClient()
    if provider == "anthropic":
        from app.llm.providers.anthropic_client import AnthropicClient

        return AnthropicClient()
    raise LLMConfigError(f"알 수 없는 LLM 공급자: {provider} (openai | google | anthropic | fake)")


class LLMRouter:
    """역할별 공급자로 호출을 넘기고, 공통 호출 규칙(재시도·시간 제한·토큰 로그)을 적용한다."""

    def __init__(self) -> None:
        self._clients: dict[str, ProviderClient] = {}

    def client(self, provider: str) -> ProviderClient:
        if provider not in self._clients:
            self._clients[provider] = _make_client(provider)
        return self._clients[provider]

    async def structured(
        self,
        *,
        role: Role,
        node: str,
        system: str,
        user: str,
        schema: type[T],
        image: bytes | None = None,
        timeout: float = 20.0,
        deterministic: bool = True,
    ) -> T:
        """구조화 출력 호출. 시간 초과·연결 실패·형식 오류는 각각 1회 재시도한다."""
        retried: set[str] = set()
        feedback = ""
        target: Target | None = None
        while True:
            started = time.perf_counter()
            status = "ok"
            reason = ""
            usage = Usage()
            try:
                target = resolve_target(role)
                client = self.client(target.provider)
                result, usage = await asyncio.wait_for(
                    client.call(
                        target=target,
                        node=node,
                        system=system,
                        user=user + feedback,
                        schema=schema,
                        image=image,
                        timeout=timeout,
                        deterministic=deterministic,
                    ),
                    timeout=timeout,
                )
                return result
            except (TimeoutError, LLMTimeout) as exc:
                status, kind, err = "timeout", "timeout", LLMTimeout(f"{node} timeout")
                err.__cause__ = exc
            except LLMNetworkError as exc:
                status, kind, err = "network", "network", exc
                reason = str(exc)[:80]
            except (LLMOutputError, ValidationError) as exc:
                status, kind = "invalid_output", "output"
                err = exc if isinstance(exc, LLMOutputError) else LLMOutputError(f"{node} output invalid")
                reason = str(err)[:80]  # 내부 사유(refusal, max_tokens 등). 문서 내용은 담기지 않는다
                feedback = "\n\n(이전 응답이 요구한 형식에 맞지 않았어요. 스키마에 정확히 맞춰 다시 답하세요.)"
            except Exception as exc:  # 설정 오류 등 재시도하지 않는 실패도 로그에는 실패로 남긴다
                status = "config" if isinstance(exc, LLMConfigError) else "error"
                reason = str(exc)[:160] if isinstance(exc, LLMConfigError) else type(exc).__name__
                raise
            finally:
                acc = current_usage.get()
                if acc is not None:
                    acc.add(usage)
                log_event(
                    "llm call",
                    sessionId=current_session_id.get(),
                    node=node,
                    role=role,
                    provider=target.provider if target else None,
                    model=target.model if target else None,
                    status=status,
                    durationMs=round((time.perf_counter() - started) * 1000),
                    tokensIn=usage.tokens_in,
                    tokensOut=usage.tokens_out,
                    **({"detail": reason} if reason else {}),
                )
            if kind in retried:
                raise err
            retried.add(kind)


_llm: LLMRouter | None = None


def get_llm() -> LLMRouter:
    global _llm
    if _llm is None:
        _llm = LLMRouter()
    return _llm


def reset_llm() -> None:
    """테스트에서 공급자 설정을 바꾼 뒤 호출."""
    global _llm
    _llm = None
