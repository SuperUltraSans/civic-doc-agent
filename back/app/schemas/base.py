"""모든 응답 스키마의 기반 모델. 프론트는 camelCase를 쓴다 (지시서 2.3절)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def to_api(self) -> dict[str, Any]:
        """응답용 직렬화: camelCase, None 필드 제외."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")
