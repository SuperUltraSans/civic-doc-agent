"""Anthropic API (공식 anthropic SDK, 구조화 출력 messages.parse). 선택 공급자 — 기본 구성에서는 쓰지 않는다.

- 주소는 설정값(LLM_ANTHROPIC_BASE_URL)으로 고정한다. SDK가 ANTHROPIC_BASE_URL 환경 변수를 읽어
  키가 다른 주소로 가는 일을 막는다.
- LLM_REFUSAL_FALLBACK 이 켜져 있으면 안전 분류기 거절 시 서버가 다른 모델로 다시 실행한다(beta).
- 최신 모델은 thinking 을 끌 수 없고 thinking 토큰도 max_tokens 에 들어간다 → 잘림(max_tokens)은 형식 오류로 처리.
"""

from __future__ import annotations

import base64
from typing import Any

from pydantic import ValidationError

from app.config import get_settings
from app.llm.base import LLMConfigError, LLMNetworkError, LLMOutputError, LLMTimeout, ProviderClient, Target, Usage
from app.logging_setup import log_event

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def sampling_supported(model_id: str) -> bool:
    """temperature를 받는 모델인지. 최신 Claude 모델은 sampling 파라미터를 받으면 400을 돌려준다."""
    mid = model_id.lower()
    rejects = ("opus-4-7", "opus-4-8", "opus-5", "sonnet-5", "fable", "mythos")
    return not any(x in mid for x in rejects)


class AnthropicClient(ProviderClient):
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        s = get_settings()
        key = s.secret(s.anthropic_api_key)
        if not key:
            raise LLMConfigError("ANTHROPIC_API_KEY 가 비어 있습니다")
        self._client = anthropic.AsyncAnthropic(api_key=key, base_url=s.llm_anthropic_base_url, max_retries=0)

    async def call(self, *, target: Target, node, system, user, schema, image, timeout, deterministic):  # type: ignore[override]
        import anthropic

        s = get_settings()
        content: list[dict[str, Any]] = []
        if image is not None:
            content.append(
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(image).decode("ascii")}}
            )
        content.append({"type": "text", "text": user})
        kwargs: dict[str, Any] = {}
        if deterministic and sampling_supported(target.model):
            # anthropic SDK 1.x 는 sampling 파라미터 인자를 없앴다 → 받는 모델에만 본문에 직접 넣는다
            kwargs["extra_body"] = {"temperature": 0}
        if target.effort:
            kwargs["output_config"] = {"effort": target.effort}
        client = self._client.with_options(timeout=timeout)
        if s.llm_refusal_fallback:
            api = client.beta.messages
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = s.llm_refusal_fallback
        else:
            api = client.messages
        try:
            resp = await api.parse(
                model=target.model,
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
            log_event("llm refusal fallback", node=node, requested=target.model, servedBy=resp.model)
        if resp.stop_reason == "refusal":
            raise LLMOutputError("refusal")
        if resp.stop_reason == "max_tokens":
            raise LLMOutputError("max_tokens (LLM_MAX_TOKENS 를 올릴 것)")
        parsed = resp.parsed_output
        if parsed is None:
            raise LLMOutputError("no parsed output")
        return parsed, usage
