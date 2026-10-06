# 출처·라이선스 (백엔드)

대회 출처 신고용. 버전은 `requirements.txt` 고정값 기준.

## 신규개발분과 기존 자산

- **신규개발분**: `back/` 전체 — 코드, 프롬프트(`app/llm/prompts`), 데이터 파일, 테스트, 스크립트, 합성 샘플 (2026-10-05 대회 기간 중 작성).
- 기존 자산: 없음 (아래 오픈소스 라이브러리만 사용).

## 라이브러리

| 이름 | 버전 | 라이선스 | 용도 |
|---|---|---|---|
| FastAPI | 0.142.2 | MIT | 웹 API |
| Starlette | 1.7.0 | BSD-3-Clause | ASGI (FastAPI 하부) |
| Uvicorn | 0.54.0 | BSD-3-Clause | ASGI 서버 |
| Pydantic | 2.13.5 | MIT | 스키마·검증 |
| pydantic-settings | 2.15.0 | MIT | 환경 변수 설정 |
| python-multipart | 0.0.32 | Apache-2.0 | 업로드 파싱 |
| LangGraph | 1.2.12 | MIT | 에이전트 흐름 (분기·되돌아가기·interrupt) |
| langchain-core | 1.6.6 | MIT | LangGraph 의존성 |
| openai | 3.24.0 | Apache-2.0 | OpenAI API — 계획·빠른 역할 (Responses API) |
| google-genai | 2.28.0 | Apache-2.0 | Google Gemini API — 문서 읽기 역할 |
| anthropic | 1.11.0 | MIT | Anthropic API (선택 공급자, 기본 구성에서는 쓰지 않음) |
| httpx | 0.28.1 | BSD-3-Clause | 공공데이터·검색 API 호출, google-genai 하부, 테스트 |
| httpx2 | 2.13.1 | BSD-3-Clause | openai SDK 하부 (의존성) |
| Pillow | 12.3.0 | MIT-CMU (HPND) | 이미지 회전 보정·리사이즈 |
| rank-bm25 | 0.2.2 | Apache-2.0 | 사칭 수법 BM25 검색 |
| numpy | 2.5.3 | BSD-3-Clause 등 | rank-bm25 의존성 |
| kiwipiepy / kiwipiepy_model | 0.24.0 | Apache-2.0 | 한국어 형태소 분석 |
| tzdata | 2026.5 | Apache-2.0 | Asia/Seoul 시간대 |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | MIT / Apache-2.0 | 테스트 |

## AI 모델

역할별로 다른 모델을 쓴다 (AWS Bedrock은 쓰지 않음). 모델 ID는 환경 변수로 지정한다.

| 역할 | 모델 | 모델 ID | 제공 |
|---|---|---|---|
| 문서 읽기 (`MODEL_VISION`) | Gemini 3.8 Flash | `gemini-3.8-flash` | Google (Gemini API) |
| 계획 (`MODEL_REASON`) | GPT-6.1 Sol | `gpt-6.1-sol` | OpenAI (API) |
| 빠른 — 설명·복지 재정렬·수법 선택 (`MODEL_FAST`) | GPT-6 Luna | `gpt-6-luna` | OpenAI (API) |

- 모델 ID는 각 사 공식 모델 문서(2026-10-06 확인: https://ai.google.dev/gemini-api/docs/models , https://developers.openai.com/api/docs/models )에서 확인했다. 제출 전 실제 실행 로그(`llm call` 의 `model`)로 다시 확인할 것.

## 외부 API

| API | 제공 | 용도 | 비고 |
|---|---|---|---|
| 한국사회보장정보원 중앙부처복지서비스 / 지자체복지서비스 | 공공데이터포털 (data.go.kr) | 복지 제도 후보 검색 | 활용 신청 필요. 이용허락 범위 확인 후 기입: `(기입)` |
| 네이버 검색 API (웹문서) | NAVER API HUB (`naverapihub.apigw.ntruss.com/search/v1/webkr`, 2026년 NAVER Developers 에서 이관) | 기관 공식 번호 실시간 검색 (`.go.kr`·공식 도메인 결과만 사용) | 선택 기능. 하루 25,000회 |
| Google Gemini API | Google | 문서 읽기(이미지) | 유료 등급 키 사용 (무료 등급은 입력이 제품 개선에 쓰일 수 있음 — 약관 확인) |
| OpenAI API | OpenAI | 계획·설명·복지 재정렬·수법 선택 | `store=False` 로 호출 |

## 데이터 파일

| 파일 | 내용 | 출처 | 상태 |
|---|---|---|---|
| `data/agencies.json` | 기관 공식 대표번호·도메인 시드 | 각 기관 공식 홈페이지 (`sourceUrl`) | ⚠ **직접 확인 전**. 번호는 널리 알려진 전국 대표번호만 넣었고 모든 항목 `checkedAt: null`. 경남 시청 번호는 비워 둠 |
| `data/terms.json` | 행정 용어 쉬운 말 풀이 33개 | 읽어드림 팀 정리 | ⚠ 국립국어원 등 공개 순화 자료와 대조 필요 |
| `data/scam_patterns.jsonl` | 사칭·스미싱 수법 45개 (KISA 23, 경찰청 12, 금감원 10) | KISA 보호나라, 경찰청, 금융감독원 공개 예방 자료를 수법 단위로 요약 | ⚠ 원문 대조, 항목별 상세 URL·공공누리 유형 기록 필요 |
| `data/shortener_domains.txt` | 단축 주소 도메인 목록 | 팀 정리 | |
| `data/welfare_snapshot.csv` | 복지 제도 사본 17개 (중앙부처) | 각 소관 기관 공개 안내를 수기 정리 | ⚠ API 활용 승인 후 `scripts/fetch_welfare.py`로 교체 권장 |
| `data/regions.json` | 지역 질문 선택지 | 팀 정리 | |
| `samples/*` | 합성 문서 이미지 7장 + 정답 JSON | `scripts/make_samples.py`로 생성, 이름·번호·계좌 모두 가상 | 실제 촬영 샘플 별도 필요 |

## 글꼴 (샘플 생성 스크립트만)

- `scripts/make_samples.py`는 로컬 시스템 글꼴(macOS Apple SD Gothic Neo 등)을 읽어 이미지를 그린다. 글꼴 파일은 저장소에 포함하지 않는다.
