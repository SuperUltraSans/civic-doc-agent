"""Anthropic 공급자(선택) 호출 규칙 — 실제 API 없이 SDK 클라이언트를 가짜로 바꿔 확인한다."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.config import get_settings
from app.llm.base import LLMOutputError, Target
from app.llm.client import reset_llm
from app.llm.providers.anthropic_client import FALLBACK_BETA, AnthropicClient
from app.llm.schemas import PlanOut


@pytest.fixture
def anthropic_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_VISION", "claude-opus-5-5")
    monkeypatch.setenv("MODEL_REASON", "claude-opus-5-5")
    monkeypatch.setenv("MODEL_FAST", "claude-sonnet-5-5")
    monkeypatch.delenv("LLM_REFUSAL_FALLBACK", raising=False)
    get_settings.cache_clear()
    reset_llm()
    yield monkeypatch
    get_settings.cache_clear()
    reset_llm()


class StubApi:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class StubClient:
    """with_options() → 자기 자신, messages / beta.messages 로 호출을 기록한다."""

    def __init__(self, response: Any) -> None:
        self.messages = StubApi(response)
        self.beta = SimpleNamespace(messages=StubApi(response))

    def with_options(self, **_: Any) -> "StubClient":
        return self


def response(stop_reason: str = "end_turn", parsed: Any = None, iterations: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, iterations=iterations),
    )


PLAN = PlanOut.model_validate({"situation": "상황", "plan": [], "needUserInfo": []})


TARGET = Target(role="reason", provider="anthropic", model="claude-opus-5-5", effort="low")


async def call(llm: AnthropicClient) -> Any:
    return await llm.call(target=TARGET, node="plan", system="s", user="u", schema=PlanOut, image=None, timeout=5, deterministic=True)


def test_base_url_ignores_anthropic_base_url_env(anthropic_env):
    anthropic_env.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9/should-not-be-used")
    llm = AnthropicClient()
    assert str(llm._client.base_url).rstrip("/") == "https://api.anthropic.com"


def test_base_url_setting(anthropic_env):
    anthropic_env.setenv("LLM_ANTHROPIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    assert str(AnthropicClient()._client.base_url).rstrip("/") == "https://example.test"


async def test_fallback_on_uses_beta_path(anthropic_env):
    llm = AnthropicClient()
    stub = StubClient(response(parsed=PLAN))
    llm._client = stub
    parsed, usage = await call(llm)
    assert parsed is PLAN and usage.tokens_in == 10
    assert not stub.messages.calls
    kwargs = stub.beta.messages.calls[0]
    assert kwargs["betas"] == [FALLBACK_BETA]
    assert kwargs["fallbacks"] == "default"
    assert kwargs["output_format"] is PlanOut
    assert kwargs["output_config"] == {"effort": "low"}
    assert "extra_body" not in kwargs  # opus-5-5 는 temperature 를 받지 않는다


async def test_fallback_off_uses_plain_path(anthropic_env):
    anthropic_env.setenv("LLM_REFUSAL_FALLBACK", "")
    get_settings.cache_clear()
    llm = AnthropicClient()
    stub = StubClient(response(parsed=PLAN))
    llm._client = stub
    await call(llm)
    assert not stub.beta.messages.calls
    kwargs = stub.messages.calls[0]
    assert "betas" not in kwargs and "fallbacks" not in kwargs


@pytest.mark.parametrize(
    ("stop_reason", "parsed", "reason"),
    [("refusal", None, "refusal"), ("max_tokens", None, "max_tokens"), ("end_turn", None, "no parsed output")],
)
async def test_unusable_responses_become_output_errors(anthropic_env, stop_reason, parsed, reason):
    llm = AnthropicClient()
    llm._client = StubClient(response(stop_reason=stop_reason, parsed=parsed))
    with pytest.raises(LLMOutputError, match=reason):
        await call(llm)


async def test_fallback_served_response_is_used(anthropic_env):
    llm = AnthropicClient()
    llm._client = StubClient(response(parsed=PLAN, iterations=[SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")]))
    parsed, _ = await call(llm)
    assert parsed is PLAN
