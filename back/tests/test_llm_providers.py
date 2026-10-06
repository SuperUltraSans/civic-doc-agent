"""역할별 공급자 (문서 읽기: Gemini, 계획·빠른: OpenAI) — 실제 API 없이 SDK에 가짜 HTTP 응답을 물려 확인한다.

- 요청 모양: 모델 ID, 시스템 프롬프트, JSON 스키마, 이미지, 사고 수준, temperature 를 보내지 않음, 저장 안 함
- 응답 처리: 구조화 출력 파싱, 토큰 수, 잘림·거절·형식 오류 → LLMOutputError
- 오류 구분: 429·5xx → 연결 오류(재시도), 4xx → 설정 오류
- 라우팅: 역할별 공급자·모델, 빈 역할은 다른 역할을 공급자와 함께 빌림, fake 우선
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import httpx2
import pytest

from app.config import get_settings
from app.llm import client as llm_client
from app.llm.base import LLMConfigError, LLMNetworkError, LLMOutputError, Target
from app.llm.client import get_llm, reset_llm, resolve_target
from app.llm.providers.gemini_client import GeminiClient, response_schema
from app.llm.providers.openai_client import OpenAIClient
from app.llm.schemas import ExtractOut, PlanOut

PLAN_JSON = {"situation": "밀린 금액이 있는 고지서예요", "plan": [{"tool": "search_welfare", "reason": "밀린 돈이 있어요"}], "needUserInfo": ["region"]}
EXTRACT_JSON = {
    "docType": "health_insurance_bill",
    "issuer": "국민건강보험공단",
    "fields": {"amount": 32500, "dueDate": "2026-10-11", "billingMonth": None, "arrears": None, "phone": "1577-1000", "url": None},
    "confidence": {"amount": 0.95, "dueDate": 0.9, "billingMonth": None, "arrears": None, "phone": 0.9, "url": None},
    "legible": True,
    "rawTextExcerpt": "납기 내 금액 32,500원",
}
IMAGE = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture
def team_env(monkeypatch: pytest.MonkeyPatch):
    """팀 결정 구성: 문서 읽기 Gemini 3.8 Flash, 계획 GPT-6.1 Sol, 빠른 GPT-6 Luna."""
    env = {
        "LLM_PROVIDER": "openai",
        "PROVIDER_VISION": "google",
        "PROVIDER_REASON": "",
        "PROVIDER_FAST": "",
        "MODEL_VISION": "gemini-3.8-flash",
        "MODEL_REASON": "gpt-6.1-sol",
        "MODEL_FAST": "gpt-6-luna",
        "OPENAI_API_KEY": "test-openai",
        "GEMINI_API_KEY": "test-gemini",
        "LLM_EFFORT": "",
        "EFFORT_VISION": "",
        "EFFORT_REASON": "",
        "EFFORT_FAST": "",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    reset_llm()
    yield monkeypatch
    get_settings.cache_clear()
    reset_llm()


def refresh() -> None:
    get_settings.cache_clear()
    reset_llm()


# ── OpenAI (Responses API) ──
def openai_response(body_text: str | None, *, status: str = "completed", incomplete: str | None = None, refusal: bool = False) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if refusal:
        content.append({"type": "refusal", "refusal": "거절"})
    elif body_text is not None:
        content.append({"type": "output_text", "text": body_text, "annotations": []})
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": status,
        "model": "gpt-6.1-sol",
        "incomplete_details": {"reason": incomplete} if incomplete else None,
        "output": [{"type": "message", "id": "msg_test", "status": "completed", "role": "assistant", "content": content}],
        "usage": {
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 10},
        },
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }


def openai_client(handler) -> tuple[OpenAIClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    return OpenAIClient(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(wrapped))), seen


SOL = Target(role="reason", provider="openai", model="gpt-6.1-sol", effort="medium")


async def test_openai_request_and_parse(team_env):
    client, seen = openai_client(lambda r: httpx2.Response(200, json=openai_response(json.dumps(PLAN_JSON, ensure_ascii=False))))
    parsed, usage = await client.call(target=SOL, node="plan", system="시스템", user="입력", schema=PlanOut, image=None, timeout=5, deterministic=True)
    assert isinstance(parsed, PlanOut) and parsed.need_user_info == ["region"]
    assert (usage.tokens_in, usage.tokens_out) == (120, 40)

    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/responses"
    assert req.headers["authorization"] == "Bearer test-openai"
    body = json.loads(req.content)
    assert body["model"] == "gpt-6.1-sol"
    assert body["instructions"] == "시스템"
    assert body["store"] is False  # 문서 내용을 OpenAI 쪽에 저장하지 않는다
    assert body["reasoning"] == {"effort": "medium"}
    assert "temperature" not in body  # 추론 모델은 temperature 를 받지 않는다
    assert body["max_output_tokens"] == get_settings().llm_max_tokens
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert set(fmt["schema"]["properties"]) == {"situation", "plan", "needUserInfo"}  # 프롬프트와 같은 camelCase


async def test_openai_image_input_and_no_effort(team_env):
    client, seen = openai_client(lambda r: httpx2.Response(200, json=openai_response(json.dumps(EXTRACT_JSON))))
    target = Target(role="vision", provider="openai", model="gpt-6-luna")
    parsed, _ = await client.call(target=target, node="extract", system="s", user="u", schema=ExtractOut, image=IMAGE, timeout=5, deterministic=True)
    assert parsed.fields.amount == 32500
    body = json.loads(seen[0].content)
    content = body["input"][0]["content"]
    assert content[0]["type"] == "input_image"
    assert content[0]["image_url"] == "data:image/jpeg;base64," + base64.b64encode(IMAGE).decode()
    assert content[1] == {"type": "input_text", "text": "u"}
    assert "reasoning" not in body  # 비우면 보내지 않는다 (공급자 기본값)


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (openai_response(None, status="incomplete", incomplete="max_output_tokens"), "max_output_tokens"),
        (openai_response(None, refusal=True), "refusal"),
        (openai_response('{"situation": 1}'), "validation|no parsed"),
    ],
)
async def test_openai_unusable_responses(team_env, response, match):
    client, _ = openai_client(lambda r: httpx2.Response(200, json=response))
    with pytest.raises(LLMOutputError, match=match):
        await client.call(target=SOL, node="plan", system="s", user="u", schema=PlanOut, image=None, timeout=5, deterministic=True)


@pytest.mark.parametrize(("status", "error"), [(429, LLMNetworkError), (503, LLMNetworkError), (400, LLMConfigError), (404, LLMConfigError)])
async def test_openai_error_mapping(team_env, status, error):
    client, _ = openai_client(lambda r: httpx2.Response(status, json={"error": {"message": "x", "type": "t", "code": None}}))
    with pytest.raises(error):
        await client.call(target=SOL, node="plan", system="s", user="u", schema=PlanOut, image=None, timeout=5, deterministic=True)


def test_openai_base_url_ignores_sdk_env(team_env):
    team_env.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/should-not-be-used")
    refresh()
    assert str(OpenAIClient()._client.base_url).rstrip("/") == "https://api.openai.com/v1"


# ── Gemini (generateContent) ──
def gemini_response(text: str | None, *, finish: str = "STOP", block: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 60, "thoughtsTokenCount": 25, "totalTokenCount": 885},
        "modelVersion": "gemini-3.8-flash",
    }
    if block:
        data["promptFeedback"] = {"blockReason": block}
    else:
        parts = [{"text": text}] if text is not None else []
        data["candidates"] = [{"content": {"role": "model", "parts": parts}, "finishReason": finish}]
    return data


def gemini_client(handler) -> tuple[GeminiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return GeminiClient(httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped))), seen


FLASH = Target(role="vision", provider="google", model="gemini-3.8-flash", effort="low")


async def test_gemini_request_and_parse(team_env):
    client, seen = gemini_client(lambda r: httpx.Response(200, json=gemini_response(json.dumps(EXTRACT_JSON, ensure_ascii=False))))
    parsed, usage = await client.call(target=FLASH, node="extract", system="판독 규칙", user="읽어 주세요", schema=ExtractOut, image=IMAGE, timeout=30, deterministic=True)
    assert parsed.doc_type == "health_insurance_bill" and parsed.fields.phone == "1577-1000"
    assert (usage.tokens_in, usage.tokens_out) == (800, 85)  # 사고 토큰도 출력에 포함

    req = seen[0]
    assert req.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
    assert req.url.host == "generativelanguage.googleapis.com"
    assert req.headers["x-goog-api-key"] == "test-gemini"
    body = json.loads(req.content)
    parts = body["contents"][0]["parts"]
    inline = parts[0].get("inlineData") or parts[0]["inline_data"]
    assert (inline.get("mimeType") or inline.get("mime_type")) == "image/jpeg"
    assert base64.urlsafe_b64decode(inline["data"]) == IMAGE
    assert parts[1] == {"text": "읽어 주세요"}
    assert body["systemInstruction"]["parts"][0]["text"] == "판독 규칙"
    gen = body["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    thinking = gen.get("thinkingConfig") or gen["thinking_config"]  # API는 camelCase·snake_case 를 모두 받는다
    assert (thinking.get("thinkingLevel") or thinking.get("thinking_level")) == "LOW"
    assert "temperature" not in gen  # Gemini 3 는 기본값(1.0) 유지 권고
    schema = gen["responseJsonSchema"]
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)  # 참조를 펼쳐 보낸다
    assert {"docType", "fields", "confidence", "legible", "rawTextExcerpt"} <= set(schema["properties"])


def test_gemini_response_schema_inlines_nested_models():
    schema = response_schema(ExtractOut)
    fields = schema["properties"]["fields"]
    assert fields["type"] == "object" and "amount" in fields["properties"]
    assert schema["properties"]["docType"]["enum"][0] == "health_insurance_bill"


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (gemini_response(None, finish="MAX_TOKENS"), "max_tokens"),
        (gemini_response(None, finish="SAFETY"), "refusal"),
        (gemini_response(None, block="PROHIBITED_CONTENT"), "refusal"),
        (gemini_response('{"docType": "nope"}'), "validation"),
        (gemini_response(""), "no parsed output"),
    ],
)
async def test_gemini_unusable_responses(team_env, response, match):
    client, _ = gemini_client(lambda r: httpx.Response(200, json=response))
    with pytest.raises(LLMOutputError, match=match):
        await client.call(target=FLASH, node="extract", system="s", user="u", schema=ExtractOut, image=IMAGE, timeout=5, deterministic=True)


@pytest.mark.parametrize(("status", "error"), [(429, LLMNetworkError), (500, LLMNetworkError), (400, LLMConfigError), (403, LLMConfigError)])
async def test_gemini_error_mapping(team_env, status, error):
    body = {"error": {"code": status, "message": "x", "status": "ERR"}}
    client, _ = gemini_client(lambda r: httpx.Response(status, json=body))
    with pytest.raises(error):
        await client.call(target=FLASH, node="extract", system="s", user="u", schema=ExtractOut, image=IMAGE, timeout=5, deterministic=True)


def test_gemini_ignores_vertex_env(team_env):
    team_env.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    refresh()
    client = GeminiClient()
    assert client._client.vertexai is False


# ── 라우팅 ──
def test_team_routing(team_env):
    assert resolve_target("vision") == Target(role="vision", provider="google", model="gemini-3.8-flash")
    assert resolve_target("reason") == Target(role="reason", provider="openai", model="gpt-6.1-sol")
    assert resolve_target("fast") == Target(role="fast", provider="openai", model="gpt-6-luna")


def test_effort_per_role_with_global_default(team_env):
    team_env.setenv("LLM_EFFORT", "low")
    team_env.setenv("EFFORT_REASON", "medium")
    refresh()
    assert resolve_target("vision").effort == "low"
    assert resolve_target("reason").effort == "medium"


def test_empty_role_borrows_another_role_with_its_provider(team_env):
    team_env.setenv("MODEL_VISION", "")
    refresh()
    target = resolve_target("vision")
    # 모델만 빌리고 공급자는 원래 역할 것을 쓰면 OpenAI 모델 ID가 Gemini 로 가는 일이 생긴다
    assert (target.provider, target.model) == ("openai", "gpt-6.1-sol")


def test_no_models_is_config_error(team_env):
    for k in ("MODEL_VISION", "MODEL_REASON", "MODEL_FAST"):
        team_env.setenv(k, "")
    refresh()
    with pytest.raises(LLMConfigError):
        resolve_target("fast")


def test_fake_overrides_role_providers(team_env):
    team_env.setenv("LLM_PROVIDER", "fake")
    refresh()
    assert resolve_target("vision").provider == "fake"


async def test_missing_key_is_config_error_not_retried(team_env):
    team_env.setenv("GEMINI_API_KEY", "")
    refresh()
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        await get_llm().structured(role="vision", node="extract", system="s", user="u", schema=ExtractOut, image=IMAGE)


async def test_router_sends_each_role_to_its_provider(team_env, monkeypatch):
    calls: list[tuple[str, str, str]] = []

    class Recorder:
        def __init__(self, provider: str) -> None:
            self.name = provider

        async def call(self, *, target, node, system, user, schema, image, timeout, deterministic):
            calls.append((node, target.provider, target.model))
            data = EXTRACT_JSON if schema is ExtractOut else PLAN_JSON
            return schema.model_validate(data), llm_client.Usage(1, 1)

    monkeypatch.setattr(llm_client, "_make_client", lambda provider: Recorder(provider))
    llm = get_llm()
    await llm.structured(role="vision", node="extract", system="s", user="u", schema=ExtractOut, image=IMAGE)
    await llm.structured(role="reason", node="plan", system="s", user="u", schema=PlanOut)
    await llm.structured(role="fast", node="explain", system="s", user="u", schema=PlanOut)
    assert calls == [
        ("extract", "google", "gemini-3.8-flash"),
        ("plan", "openai", "gpt-6.1-sol"),
        ("explain", "openai", "gpt-6-luna"),
    ]


@pytest.mark.parametrize("level, expected", [("", None), ("medium", "MEDIA_RESOLUTION_MEDIUM"), ("ultra_high", "MEDIA_RESOLUTION_ULTRA_HIGH")])
async def test_gemini_media_resolution(team_env, level, expected):
    """이미지 해상도 설정: 비우면 보내지 않고(기본 = high), 정하면 이미지 부분에 붙인다."""
    team_env.setenv("GEMINI_MEDIA_RESOLUTION", level)
    refresh()
    client, seen = gemini_client(lambda r: httpx.Response(200, json=gemini_response(json.dumps(EXTRACT_JSON))))
    await client.call(target=FLASH, node="extract", system="s", user="u", schema=ExtractOut, image=IMAGE, timeout=5, deterministic=True)
    part = json.loads(seen[0].content)["contents"][0]["parts"][0]
    res = part.get("mediaResolution") or part.get("media_resolution")
    assert (res.get("level") if res else None) == expected
