"""OpenAI API (공식 openai SDK, Responses API 구조화 출력 responses.parse).

기본 구성에서 계획(reason: GPT-6.1 Sol)·빠른(fast: GPT-6 Luna) 역할을 맡는다.
- 주소는 설정값(LLM_OPENAI_BASE_URL)으로 고정한다. SDK가 OPENAI_BASE_URL 환경 변수를 따라가지 않게 한다.
- store=False: 문서 내용이 담긴 요청·응답을 OpenAI 쪽에 저장하지 않는다 (개인정보, 지시서 8장).
- 추론 모델(GPT-5 이후)은 temperature 를 받지 않으므로 보내지 않고, 사고 수준은 reasoning.effort 로 정한다.
"""

from __future__ import annotations

import base64
from typing import Any

from pydantic import ValidationError

from app.config import get_settings
from app.llm.base import LLMConfigError, LLMNetworkError, LLMOutputError, LLMTimeout, ProviderClient, Target, Usage

# temperature 를 받는 (추론 모델이 아닌) 모델 접두사
_SAMPLING_PREFIXES = ("gpt-4", "gpt-3.5")


def sampling_supported(model_id: str) -> bool:
    return model_id.lower().startswith(_SAMPLING_PREFIXES)


class OpenAIClient(ProviderClient):
    name = "openai"

    def __init__(self, http_client: Any = None) -> None:
        import openai

        s = get_settings()
        key = s.secret(s.openai_api_key)
        if not key:
            raise LLMConfigError("OPENAI_API_KEY 가 비어 있습니다")
        self._client = openai.AsyncOpenAI(
            api_key=key,
            base_url=s.llm_openai_base_url,
            max_retries=0,  # 재시도는 LLMRouter 가 한다
            **({"http_client": http_client} if http_client is not None else {}),
        )

    async def call(self, *, target: Target, node, system, user, schema, image, timeout, deterministic):  # type: ignore[override]
        import openai

        s = get_settings()
        content: list[dict[str, Any]] = []
        if image is not None:
            b64 = base64.b64encode(image).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}", "detail": "high"})
        content.append({"type": "input_text", "text": user})
        kwargs: dict[str, Any] = {}
        if target.effort:
            kwargs["reasoning"] = {"effort": target.effort}
        if deterministic and sampling_supported(target.model):
            kwargs["temperature"] = 0
        try:
            resp = await self._client.with_options(timeout=timeout).responses.parse(
                model=target.model,
                instructions=system,
                input=[{"role": "user", "content": content}],
                text_format=schema,
                max_output_tokens=s.llm_max_tokens,
                store=False,
                **kwargs,
            )
        except openai.APITimeoutError as exc:
            raise LLMTimeout("APITimeoutError") from exc
        except openai.APIConnectionError as exc:
            raise LLMNetworkError("APIConnectionError") from exc
        except (openai.RateLimitError, openai.InternalServerError) as exc:
            raise LLMNetworkError(type(exc).__name__) from exc
        except openai.APIStatusError as exc:
            # 키·모델 ID·파라미터 오류. 문구는 로그에만 남긴다 (사용자에게 보내지 않음)
            raise LLMConfigError(f"APIStatusError {exc.status_code}: {exc.message}"[:160]) from exc
        except ValidationError as exc:
            raise LLMOutputError("validation failed") from exc
        usage = Usage(resp.usage.input_tokens or 0, resp.usage.output_tokens or 0) if resp.usage else Usage()
        if resp.status == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", None) or "unknown"
            hint = " (LLM_MAX_TOKENS 를 올릴 것)" if reason == "max_output_tokens" else ""
            raise LLMOutputError(f"incomplete: {reason}{hint}")
        parsed = resp.output_parsed
        if parsed is None:
            refused = any(
                getattr(part, "type", None) == "refusal"
                for item in resp.output or []
                for part in getattr(item, "content", None) or []
            )
            raise LLMOutputError("refusal" if refused else "no parsed output")
        return parsed, usage
