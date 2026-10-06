"""Google Gemini API (공식 google-genai SDK, generateContent + JSON 스키마 출력).

기본 구성에서 문서 읽기(vision: Gemini 3.8 Flash) 역할을 맡는다.
- Gemini API(AI Studio 키)만 쓴다. GOOGLE_GENAI_USE_VERTEXAI 같은 환경 변수로 Vertex AI 로 바뀌지 않게 고정한다.
- Gemini 3 계열은 temperature 를 기본값 1.0 에서 바꾸지 말라는 것이 공식 권고(바꾸면 반복·품질 저하)라 보내지 않는다.
  사고 수준은 thinking_level(low | medium | high)로 정한다.
- 응답은 JSON 문자열로 받아 Pydantic 으로 직접 검증한다.
"""

from __future__ import annotations

import copy
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.base import LLMConfigError, LLMNetworkError, LLMOutputError, LLMTimeout, ProviderClient, Target, Usage

# temperature 를 바꿔도 되는 모델 접두사 (Gemini 3 이후는 기본값 유지 권고)
_SAMPLING_PREFIXES = ("gemini-1", "gemini-2")
_REFUSAL_REASONS = {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}


def sampling_supported(model_id: str) -> bool:
    return model_id.lower().startswith(_SAMPLING_PREFIXES)


def response_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Pydantic 모델 → Gemini 응답 JSON 스키마. $defs 참조를 펼쳐 한 덩어리로 만든다."""
    raw = schema.model_json_schema(by_alias=True)
    defs = raw.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return inline(copy.deepcopy(defs[ref.split("/")[-1]]))
            return {k: inline(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return inline(raw)


class GeminiClient(ProviderClient):
    name = "google"

    def __init__(self, httpx_async_client: httpx.AsyncClient | None = None) -> None:
        from google import genai
        from google.genai import types

        s = get_settings()
        key = s.secret(s.gemini_api_key)
        if not key:
            raise LLMConfigError("GEMINI_API_KEY 가 비어 있습니다")
        options: dict[str, Any] = {"base_url": s.llm_gemini_base_url}
        if httpx_async_client is not None:
            options["httpx_async_client"] = httpx_async_client
        self._client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(**options))

    async def call(self, *, target: Target, node, system, user, schema, image, timeout, deterministic):  # type: ignore[override]
        from google.genai import errors, types

        s = get_settings()
        parts: list[Any] = []
        if image is not None:
            level = s.gemini_media_resolution
            resolution = types.PartMediaResolution(level=f"MEDIA_RESOLUTION_{level.upper()}") if level else None
            parts.append(types.Part.from_bytes(data=image, mime_type="image/jpeg", media_resolution=resolution))
        parts.append(types.Part.from_text(text=user))
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=response_schema(schema),
            max_output_tokens=s.llm_max_tokens,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # 도구를 쓰지 않는다
        )
        if target.effort:
            config.thinking_config = types.ThinkingConfig(thinking_level=target.effort)
        if deterministic and sampling_supported(target.model):
            config.temperature = 0
        try:
            resp = await self._client.aio.models.generate_content(
                model=target.model, contents=[types.Content(role="user", parts=parts)], config=config
            )
        except errors.ClientError as exc:
            if exc.code == 429:  # 요청 한도 — 잠시 뒤 다시 하면 된다
                raise LLMNetworkError("RateLimit 429") from exc
            raise LLMConfigError(f"ClientError {exc.code}: {exc.message}"[:160]) from exc
        except errors.ServerError as exc:
            raise LLMNetworkError(f"ServerError {exc.code}") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeout(type(exc).__name__) from exc
        except httpx.TransportError as exc:
            raise LLMNetworkError(type(exc).__name__) from exc
        meta = resp.usage_metadata
        usage = (
            Usage(meta.prompt_token_count or 0, (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0))
            if meta
            else Usage()
        )
        if resp.prompt_feedback is not None and resp.prompt_feedback.block_reason:
            raise LLMOutputError(f"refusal: blocked {resp.prompt_feedback.block_reason}")
        candidate = resp.candidates[0] if resp.candidates else None
        finish = str(getattr(candidate, "finish_reason", "") or "").rsplit(".", 1)[-1]
        if finish == "MAX_TOKENS":
            raise LLMOutputError("max_tokens (LLM_MAX_TOKENS 를 올릴 것)")
        if finish in _REFUSAL_REASONS:
            raise LLMOutputError(f"refusal: {finish}")
        text = resp.text
        if not text:
            raise LLMOutputError("no parsed output")
        try:
            return schema.model_validate_json(text), usage
        except ValidationError as exc:
            raise LLMOutputError("validation failed") from exc
