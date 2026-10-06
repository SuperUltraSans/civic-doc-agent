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

    # LLM — 역할마다 공급자·모델을 따로 고른다 (app/llm/client.py). AWS(Bedrock)는 쓰지 않는다.
    # 기본 공급자. 역할별 PROVIDER_* 가 비어 있으면 이 값을 쓴다. fake 면 모든 역할이 기록된 응답을 쓴다.
    llm_provider: Literal["openai", "google", "anthropic", "fake"] = "openai"
    provider_vision: Literal["", "openai", "google", "anthropic"] = ""  # 문서 읽기 (이미지 입력)
    provider_reason: Literal["", "openai", "google", "anthropic"] = ""  # 계획
    provider_fast: Literal["", "openai", "google", "anthropic"] = ""  # 설명·복지 재정렬·수법 선택
    # 모델 ID는 코드에 쓰지 않는다 (지시서 7.2, 13장)
    model_vision: str = ""
    model_reason: str = ""
    model_fast: str = ""
    # 사고 수준. 비우면 보내지 않는다(공급자 기본값). 역할별 EFFORT_* 가 비어 있으면 LLM_EFFORT.
    # openai: reasoning.effort (none·low·medium·high…), google: thinking_level (low·medium·high), anthropic: effort
    llm_effort: str = ""
    effort_vision: str = ""
    effort_reason: str = ""
    effort_fast: str = ""
    llm_max_tokens: int = 8000  # 최신 모델은 사고(thinking/reasoning) 토큰도 여기에 포함된다

    # 공급자별 키와 주소. SDK가 OPENAI_BASE_URL·ANTHROPIC_BASE_URL 같은 환경 변수를 따라가 키가 엉뚱한 주소로
    # 가지 않도록 주소를 명시한다 (필드 이름을 SDK 변수와 다르게 둔다).
    openai_api_key: SecretStr | None = None
    llm_openai_base_url: str = "https://api.openai.com/v1"
    gemini_api_key: SecretStr | None = None
    # Gemini 3 이미지 해상도(이미지당 토큰): low 280 | medium 560 | high 1120 | ultra_high 2240. 비우면 보내지 않음(= high 와 같음)
    gemini_media_resolution: Literal["", "low", "medium", "high", "ultra_high"] = ""
    llm_gemini_base_url: str = "https://generativelanguage.googleapis.com/"
    anthropic_api_key: SecretStr | None = None
    llm_anthropic_base_url: str = "https://api.anthropic.com"
    # anthropic 전용: 안전 분류기가 거절하면 서버가 다른 모델로 다시 실행 (비우면 끔)
    llm_refusal_fallback: str = "default"

    # 외부 데이터
    data_go_kr_service_key: SecretStr | None = None
    # 네이버 웹문서 검색 키. hub = NAVER API HUB (기본, 2026년 이관 후 발급 키), developers = 예전 개발자센터 키
    naver_search_api: Literal["hub", "developers"] = "hub"
    naver_client_id: SecretStr | None = None
    naver_client_secret: SecretStr | None = None
    external_timeout_seconds: float = 5.0

    # 사진 품질 사전 점검 (너무 작음·어두움·밝음·흐림이면 LLM 호출 없이 다시 찍기). 오작동하면 false
    photo_check_enabled: bool = True

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
