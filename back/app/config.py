"""환경 변수 설정 (pydantic-settings).

모든 설정은 환경 변수로만 받는다. 로컬 개발에서는 back/.env 파일도 읽는다.
모델 ID·API 키는 코드에 쓰지 않는다 (지시서 7.2, 13장).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 공통
    app_env: str = "development"
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:3000,http://localhost:5173"  # 쉼표로 여러 개 지정 가능 (front 컨테이너, Vite 개발 서버)
    tz_name: str = "Asia/Seoul"

    # 에이전트
    agent_mode: Literal["live", "scripted"] = "live"
    llm_provider: Literal["bedrock", "anthropic", "fake"] = "bedrock"
    model_vision: str = ""
    model_reason: str = ""
    model_fast: str = ""
    # 비워 두면 보내지 않는다. 최신 모델(Opus 5.5 등)에서 응답 속도를 낮추려면 low.
    llm_effort: str = ""
    llm_max_tokens: int = 4096
    # Bedrock 구조화 출력 방식: json_schema(기본, 강제 tool_choice를 쓰지 않음) | function_calling
    bedrock_structured_method: Literal["json_schema", "function_calling"] = "json_schema"

    # Bedrock
    aws_region: str = ""
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None

    # Anthropic API (대안)
    anthropic_api_key: SecretStr | None = None
    # SDK가 ANTHROPIC_BASE_URL 환경 변수를 자동으로 읽지 않도록 주소를 명시한다.
    # (필드 이름을 anthropic_base_url 로 하면 pydantic-settings가 같은 변수를 읽으므로 이름을 달리 둔다)
    llm_api_base_url: str = "https://api.anthropic.com"
    # 안전 분류기가 거절하면 서버가 다른 모델로 다시 실행 (default = 거절 종류에 따라 자동 선택, 비우면 끔)
    llm_refusal_fallback: str = "default"

    # 외부 데이터
    data_go_kr_service_key: SecretStr | None = None
    naver_client_id: SecretStr | None = None
    naver_client_secret: SecretStr | None = None
    external_timeout_seconds: float = 5.0

    # 세션
    session_ttl_seconds: int = 600
    session_linger_seconds: int = 120
    result_ttl_seconds: int = 1800
    answer_timeout_seconds: int = 180
    max_concurrent_sessions: int = 20
    rate_limit_per_minute: int = 20
    sse_ping_seconds: float = 15.0

    # scripted 모드 재생 속도: normal(단계당 0.8~2초) | fast(단계당 0.2초)
    scripted_speed: Literal["normal", "fast"] = "normal"

    # 저장 경로 (기관 캐시·복지 사본용 SQLite. 개인정보는 넣지 않는다)
    data_dir: Path = BASE_DIR / "data"
    db_path: Path | None = None

    @property
    def frontend_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def sqlite_path(self) -> Path:
        return self.db_path or (self.data_dir / "app.db")

    @staticmethod
    def secret(value: SecretStr | None) -> str:
        return value.get_secret_value() if value else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
