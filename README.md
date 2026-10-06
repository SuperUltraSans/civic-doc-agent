# civic-doc-agent (읽어드림)
고령층 등 디지털 취약계층을 위한 행정문서 해독 및 정리 AI 에이전트. 고지서•안내문을 촬영하면 LLM이 핵심 정보를 추출해 쉬운 말로 설명하고, 문서 내용에 따라 복지•감면 제도, 기한 관리, 사칭 여부 확인 등 필요한 후속 조치를 안내합니다.

## 개발 환경 실행

```bash
cp .env.example .env        # 포트·모드·API 키 (커밋 금지)
docker compose up --build   # front: localhost:3000, back: localhost:8000 (포트는 .env 로 변경)
docker compose down
```

- **back**: FastAPI + LangGraph 에이전트 API. 실행·환경 변수·API는 [`back/README.md`](back/README.md) 참고.
- **front**: Vite + React + TypeScript 모바일 웹. 개발 서버가 `/api`를 back 컨테이너로 프록시한다. [`front/README.md`](front/README.md) 참고.
- 포트는 기본으로 `127.0.0.1`에만 열린다. 같은 와이파이의 휴대폰으로 시험하려면 `.env`에 `BIND_ADDR=0.0.0.0`. 다른 서비스와 포트가 겹치면 `BACK_PORT`·`FRONT_PORT`를 바꾼다.
- LLM API 키(문서 읽기 Gemini 3.8 Flash, 계획 GPT-6.1 Sol, 빠른 GPT-6 Luna)를 넣기 전에는 `.env`에 `AGENT_MODE=scripted`(정해진 시나리오 재생) 또는 `VITE_USE_MOCK=true`(프론트 목업)로 화면 흐름을 시험할 수 있다. 둘 다 **실제 동작이 아니다**.

채워야 할 값(OpenAI·Gemini API 키, 공공데이터 키, 기관 번호 확인 등)은 [`사용자_확인_필요_목록.md`](사용자_확인_필요_목록.md)에 모아 두었다.

## 배포 (HTTPS 엣지)

https://kimanyfootcleaner.asuscomm.com/civic-doc-agent/

```bash
docker compose -f compose.prod.yaml up -d --build   # 키·모드는 같은 루트 .env 에서 읽는다
docker compose -f compose.prod.yaml down
```

- HTTPS 리버스 프록시(엣지)가 TLS를 종료하고 경로로 넘긴다. 앱은 포트를 공개하지 않고, 엣지와 같은 외부 Docker 네트워크 `edge-net`에만 붙는다(이름이 다르면 `compose.prod.yaml`에서 바꾼다). 엣지에는 아래 두 경로 규칙만 있으면 된다.
  - `/civic-doc-agent/api/` → `civic-doc-agent-back:8000` (프리픽스 제거, SSE를 위해 응답 버퍼링 끔·읽기 제한 300초, 업로드 11MB)
  - `/civic-doc-agent/` → `civic-doc-agent-front:80` (프리픽스 제거, 빌드된 정적 파일을 nginx로 서빙)
- 프론트는 `BASE_PATH=/civic-doc-agent/`로 빌드한다(`front/Dockerfile.prod`). 자산 경로·라우터·API 주소가 모두 이 경로를 따라간다.
- 개발용 `docker-compose.yml`과 프로젝트 이름(`civic-doc-agent-prod`)·컨테이너 이름이 달라 동시에 띄워도 겹치지 않는다.
- OpenAI·Gemini 키가 없으면 `.env`의 `AGENT_MODE=scripted`(정해진 시나리오 재생, 실제 동작 아님)로 띄울 수 있다. 실제 분석은 키를 넣고 `AGENT_MODE=live`로 바꾼 뒤 `docker compose -f compose.prod.yaml up -d back`.
