"""LLM 공급자 전환 (bedrock / anthropic / fake) — 지시서 7장.

그래프·노드 코드는 공급자를 모른다. 노드는 `get_llm().structured(...)` 하나만 쓴다.

호출 규칙 (지시서 7.3):
- 출력은 모두 구조화 출력 + Pydantic 검증. 검증 실패 시 1회 재시도.
- 시간 제한: extract 30초, 그 외 20초. 시간 초과·연결 실패는 1회 재시도.
- 노드별 소요 시간과 입력·출력 토큰 수를 로그에 남긴다.

temperature: 지시서는 추출·계획·판정 호출에 temperature 0을 요구한다. 그러나 최신 Claude 모델
(Opus 4.7 이상, Sonnet 5 이상, Fable 계열)은 temperature 값을 받으면 400을 돌려준다.
그래서 모델이 받는 경우에만 0을 보내고, 받지 않는 모델에서는 구조화 출력으로 일관성을 확보한다.
"""

from __future__ import annotations

import asyncio
import base64
import time
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.logging_setup import log_event

Role = Literal["vision", "reason", "fast"]
T = TypeVar("T", bound=BaseModel)

PROMPT_DIR = Path(__file__).parent / "prompts"

# fake 공급자가 시나리오별 응답을 고를 때 쓴다 (세션 실행 시 설정).
current_scenario: ContextVar[str] = ContextVar("current_scenario", default="arrears")
# 단계(step)별 토큰 집계용. events.step_scope 가 설정한다.
current_usage: ContextVar["Usage | None"] = ContextVar("current_usage", default=None)
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)


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


@lru_cache
def load_prompt(name: str) -> str:
    """prompts/{name}.md 를 읽는다. 상단 버전 주석(<!-- -->)은 빼고 보낸다."""
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("<!--")]
    return "\n".join(lines).strip()


def sampling_supported(model_id: str) -> bool:
    """temperature를 받는 모델인지. 최신 모델은 sampling 파라미터를 거부한다."""
    mid = model_id.lower()
    rejects = ("opus-4-7", "opus-4-8", "opus-5", "sonnet-5", "fable", "mythos")
    return not any(x in mid for x in rejects)


def model_for(role: Role) -> str:
    s = get_settings()
    preferred = {"vision": s.model_vision, "reason": s.model_reason, "fast": s.model_fast}[role]
    for candidate in (preferred, s.model_vision, s.model_reason, s.model_fast):
        if candidate:
            return candidate
    raise LLMConfigError("모델 ID 환경 변수(MODEL_VISION / MODEL_REASON / MODEL_FAST)가 비어 있습니다")


class StructuredLLM(ABC):
    provider: str = "base"

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
        while True:
            started = time.perf_counter()
            status = "ok"
            reason = ""
            usage = Usage()
            try:
                result, usage = await asyncio.wait_for(
                    self._call(
                        role=role,
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
                    provider=self.provider,
                    role=role,
                    status=status,
                    durationMs=round((time.perf_counter() - started) * 1000),
                    tokensIn=usage.tokens_in,
                    tokensOut=usage.tokens_out,
                    **({"detail": reason} if reason else {}),
                )
            if kind in retried:
                raise err
            retried.add(kind)

    @abstractmethod
    async def _call(
        self,
        *,
        role: Role,
        node: str,
        system: str,
        user: str,
        schema: type[T],
        image: bytes | None,
        timeout: float,
        deterministic: bool,
    ) -> tuple[T, Usage]: ...


class BedrockLLM(StructuredLLM):
    """Amazon Bedrock (langchain-aws ChatBedrockConverse)."""

    provider = "bedrock"

    def __init__(self) -> None:
        self._models: dict[tuple[str, bool, float], Any] = {}

    def _model(self, model_id: str, deterministic: bool, timeout: float) -> Any:
        key = (model_id, deterministic, timeout)
        if key not in self._models:
            from botocore.config import Config
            from langchain_aws import ChatBedrockConverse

            s = get_settings()
            kwargs: dict[str, Any] = {
                "model": model_id,
                "max_tokens": s.llm_max_tokens,
                "config": Config(
                    connect_timeout=5,
                    read_timeout=max(int(timeout), 5),
                    retries={"max_attempts": 1, "mode": "standard"},
                ),
            }
            if s.aws_region:
                kwargs["region_name"] = s.aws_region
            # 키가 비어 있으면 넘기지 않는다 → boto3 기본 자격 증명 체인(IAM 역할 등)을 쓴다
            if s.secret(s.aws_access_key_id) and s.secret(s.aws_secret_access_key):
                kwargs["aws_access_key_id"] = s.aws_access_key_id
                kwargs["aws_secret_access_key"] = s.aws_secret_access_key
                if s.secret(s.aws_session_token):
                    kwargs["aws_session_token"] = s.aws_session_token
            if deterministic and sampling_supported(model_id):
                kwargs["temperature"] = 0
            self._models[key] = ChatBedrockConverse(**kwargs)
        return self._models[key]

    async def _call(self, *, role, node, system, user, schema, image, timeout, deterministic):  # type: ignore[override]
        from botocore.exceptions import (
            ClientError,
            ConnectionClosedError,
            ConnectTimeoutError,
            EndpointConnectionError,
            ReadTimeoutError,
        )
        from langchain_core.messages import HumanMessage, SystemMessage

        model_id = model_for(role)
        try:
            llm = self._model(model_id, deterministic, timeout).with_structured_output(
                schema, include_raw=True, method=get_settings().bedrock_structured_method
            )
        except Exception as exc:  # 리전·자격 증명 누락 등 클라이언트 생성 실패
            raise LLMConfigError(f"Bedrock client: {type(exc).__name__}") from exc
        content: list[dict[str, Any]] = []
        if image is not None:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": user})
        try:
            out = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=content)])
        except (ReadTimeoutError, ConnectTimeoutError) as exc:
            raise LLMTimeout(str(type(exc).__name__)) from exc
        except (EndpointConnectionError, ConnectionClosedError) as exc:
            raise LLMNetworkError(type(exc).__name__) from exc
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"ThrottlingException", "ServiceUnavailableException", "InternalServerException", "ModelNotReadyException"}:
                raise LLMNetworkError(code) from exc
            if code in {"ModelTimeoutException"}:
                raise LLMTimeout(code) from exc
            raise LLMConfigError(code or "ClientError") from exc
        raw = out.get("raw") if isinstance(out, dict) else None
        meta = getattr(raw, "usage_metadata", None) or {}
        usage = Usage(int(meta.get("input_tokens", 0) or 0), int(meta.get("output_tokens", 0) or 0))
        parsed = out.get("parsed") if isinstance(out, dict) else None
        if parsed is None:
            raise LLMOutputError("structured output parsing failed")
        if not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed)
        return parsed, usage


FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM(StructuredLLM):
    """Anthropic API 직접 호출 (공식 anthropic SDK, 구조화 출력 messages.parse).

    - 주소는 설정값(LLM_API_BASE_URL)으로 고정한다. SDK가 ANTHROPIC_BASE_URL 환경 변수를 읽어
      키가 다른 주소로 가는 일을 막는다.
    - LLM_REFUSAL_FALLBACK 이 켜져 있으면 안전 분류기 거절 시 서버가 다른 모델로 다시 실행한다(beta).
    - 최신 모델은 thinking 을 끌 수 없고 thinking 토큰도 max_tokens 에 들어간다 → 잘림(max_tokens)은 형식 오류로 처리.
    """

    provider = "anthropic"

    def __init__(self) -> None:
        import anthropic

        s = get_settings()
        self._client = anthropic.AsyncAnthropic(
            api_key=s.secret(s.anthropic_api_key) or None,
            base_url=s.llm_api_base_url,
            max_retries=0,  # 재시도는 structured() 가 한다
        )

    async def _call(self, *, role, node, system, user, schema, image, timeout, deterministic):  # type: ignore[override]
        import anthropic

        s = get_settings()
        model_id = model_for(role)
        content: list[dict[str, Any]] = []
        if image is not None:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": user})
        kwargs: dict[str, Any] = {}
        if deterministic and sampling_supported(model_id):
            # anthropic SDK 1.x 는 sampling 파라미터 인자를 없앴다 → 받는 모델에만 본문에 직접 넣는다
            kwargs["extra_body"] = {"temperature": 0}
        if s.llm_effort:
            kwargs["output_config"] = {"effort": s.llm_effort}
        client = self._client.with_options(timeout=timeout)
        if s.llm_refusal_fallback:
            api = client.beta.messages
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = s.llm_refusal_fallback
        else:
            api = client.messages
        try:
            resp = await api.parse(
                model=model_id,
                max_tokens=s.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=schema,
                **kwargs,
            )
        except anthropic.APITimeoutError as exc:
            raise LLMTimeout("APITimeoutError") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMNetworkError("APIConnectionError") from exc
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise LLMNetworkError(type(exc).__name__) from exc
        except anthropic.APIStatusError as exc:
            # API 오류 문구(예: 지원하지 않는 파라미터)는 원인 파악용으로 로그에만 남긴다. 사용자에게는 보내지 않는다.
            raise LLMConfigError(f"APIStatusError {exc.status_code}: {exc.message}"[:160]) from exc
        except ValidationError as exc:
            raise LLMOutputError("validation failed") from exc
        usage = Usage(resp.usage.input_tokens or 0, resp.usage.output_tokens or 0)
        if any(getattr(it, "type", None) == "fallback_message" for it in getattr(resp.usage, "iterations", None) or []):
            log_event("llm refusal fallback", sessionId=current_session_id.get(), node=node, requested=model_id, servedBy=resp.model)
        if resp.stop_reason == "refusal":
            raise LLMOutputError("refusal")
        if resp.stop_reason == "max_tokens":
            raise LLMOutputError("max_tokens (LLM_MAX_TOKENS 를 올릴 것)")
        parsed = resp.parsed_output
        if parsed is None:
            raise LLMOutputError("no parsed output")
        return parsed, usage


class FakeLLM(StructuredLLM):
    """테스트·초기 연동용. 시나리오별로 미리 기록한 응답을 돌려준다 (app/llm/fake.py)."""

    provider = "fake"

    async def _call(self, *, role, node, system, user, schema, image, timeout, deterministic):  # type: ignore[override]
        from app.llm.fake import fake_response

        await asyncio.sleep(0.01)
        data = fake_response(node=node, scenario=current_scenario.get(), user=user)
        return schema.model_validate(data), Usage(len(system) // 4 + len(user) // 4, 200)


_llm: StructuredLLM | None = None


def get_llm() -> StructuredLLM:
    global _llm
    if _llm is None:
        provider = get_settings().llm_provider
        if provider == "bedrock":
            _llm = BedrockLLM()
        elif provider == "anthropic":
            _llm = AnthropicLLM()
        else:
            _llm = FakeLLM()
    return _llm


def reset_llm() -> None:
    """테스트에서 공급자 설정을 바꾼 뒤 호출."""
    global _llm
    _llm = None
