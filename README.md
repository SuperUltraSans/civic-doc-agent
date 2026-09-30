# civic-doc-agent
고령층 등 디지털 취약계층을 위한 행정문서 해독 및 정리 AI 에이전트. 고지서•안내문을 촬영하면 LLM이 핵심 정보를 추출해 쉬운 말로 설명하고, 문서 내용에 따라 복지•감면 제도, 기한 관리, 사칭 여부 확인 등 필요한 후속 조치를 안내합니다.

## 개발 환경 실행

```bash
docker compose up --build   # back: localhost:8000, front: localhost:3000
docker compose down
```

> ⚠️ 프론트·백엔드 프레임워크 미정 상태로, 현재는 임시 서버가 실행됩니다.
> 프레임워크 확정 시 `back/Dockerfile`, `front/Dockerfile`의 `CMD`를 교체하세요 (파일 내 예시 참고).
> 백엔드가 Python이 아니면 `FROM` 베이스 이미지도 변경 필요.
