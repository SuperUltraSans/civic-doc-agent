# 읽어드림 백엔드 (에이전트 API)

고령자가 찍은 행정문서를 읽고, 쉬운 말 설명 + 사칭 확인·기한 정리·복지 연계를 판단해 **할 일 카드**로 정리하는 에이전트 API.
`읽어드림_백엔드_구현지시서.md` 기준으로 구현했고, 응답 JSON은 `읽어드림_프론트_구현지시서.md` 5장 타입과 같다(camelCase).

- 스택: Python 3.12(로컬 3.14에서도 테스트) · FastAPI · LangGraph · langchain-aws(Bedrock) / anthropic SDK · SQLite · BM25(kiwipiepy)
- 신규개발분: 이 디렉터리 전체 (2026-10-05 대회 기간 중 작성)

## 실행

```bash
cd back
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env              # 값 채우기
.venv/bin/uvicorn app.main:app --port 8000
```

Docker (컨테이너 안에서 `0.0.0.0:8000`, 설정은 전부 환경 변수):

```bash
docker compose up --build         # 저장소 루트의 docker-compose.yml (back: 8000, front: 3000)
```

> 루트 compose는 `./back`을 컨테이너 `/app`에 마운트하므로 `back/.env`가 그대로 읽힌다. 루트 `.env`(compose `env_file`)에 넣어도 된다.
>
> 세션·SSE 버퍼가 프로세스 메모리에 있으므로 **워커는 1개**로 둔다 (Dockerfile 기본값).

### 동작 모드

| 설정 | 용도 |
|---|---|
| `AGENT_MODE=scripted` | 프론트 목업과 같은 시나리오 키(`arrears`, `blurry`, `smishing`, `local_tax`, `error`)의 이벤트를 **재생**. LLM 없이 실제 SSE 연동 시험용. `POST /api/analyze`의 `scenario` 폼 필드로 고른다. **실제 동작이 아님** — 제출 문서에서 구분해 적을 것 |
| `AGENT_MODE=live` + `LLM_PROVIDER=fake` | 실제 그래프·도구·규칙이 돌고, LLM 응답만 시나리오별 기록값(`app/llm/fake.py`). 통합 테스트용 |
| `AGENT_MODE=live` + `LLM_PROVIDER=bedrock` | 기본. Amazon Bedrock의 Claude (`MODEL_VISION/REASON/FAST`) |
| `AGENT_MODE=live` + `LLM_PROVIDER=anthropic` | Bedrock 접근이 막혔을 때의 대안 (공식 anthropic SDK) |

`LLM_PROVIDER=anthropic` 관련 설정:

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LLM_API_BASE_URL` | `https://api.anthropic.com` | SDK가 `ANTHROPIC_BASE_URL` 환경 변수(예: 다른 도구가 설정한 프록시)를 따라가 키가 엉뚱한 주소로 가지 않게 주소를 고정 |
| `LLM_REFUSAL_FALLBACK` | `default` | 안전 분류기가 거절하면 서버가 다른 모델로 다시 실행(beta `server-side-fallback-2026-07-01`). 비우면 끔 — 거절은 노드별 대체 경로로 처리 |
| `LLM_EFFORT` | (비움) | `low` 권장. Opus 5.5·Sonnet 5.5는 thinking을 끌 수 없어 effort로 시간을 줄인다 |
| `LLM_MAX_TOKENS` | `8000` | thinking 토큰도 여기에 포함된다. 너무 낮으면 출력이 잘려(`max_tokens`) 형식 오류로 처리된다 |

## API

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `POST /api/analyze` | multipart: `image`(jpeg/png/webp, 10MB 이하), `profile`(JSON 문자열, 선택), `scenario`(선택) | `{ "sessionId" }` · 그 외 이미지는 415 `unsupported_image` |
| `GET /api/analyze/{id}/events` | — | SSE: `step` · `plan` · `need_info` · `need_retake` · `result` · `error` (15초마다 `: ping`) |
| `POST /api/analyze/{id}/answer` | `{ "field": "region", "value": "김해시" \| null }` | 204 (질문 대기 중이 아니면 409) |
| `POST /api/simplify` | `{ "docId" }` | `Explanation` (level 2) · 만료 404 |
| `GET /api/health` | — | `{ "status": "ok" }` |

- 그래프는 `POST /api/analyze` 즉시 시작하고 이벤트를 세션 버퍼에 쌓는다. `/events` 연결 시 버퍼부터 보낸다 → 연결이 늦어도 유실 없음.
- `need_info` 후 `/answer`가 없으면 3분 뒤 건너뛰기(null)로 진행. 세션은 종료 후 2분 / 생성 후 10분에 삭제.
- `/api/simplify`용으로 추출 결과(연락처·주소 제거)와 설명만 30분 보관. 이미지는 보관하지 않는다.
- 오류 `message`는 항상 사용자에게 그대로 보여줄 수 있는 문장이다.

### 프론트 연동 메모

- `TodoAction.call.tel`은 사람이 읽는 형식(`1577-1000`)으로 보낸다. `tel:` 링크는 숫자만 남겨 만든다(프론트 9.6절).
- 단계 id: `read_text`, `classify`, `validate`, `explain`(tool `lookup_terms`), `plan`, `impersonation`, `deadline`, `welfare`, `evaluate`, `compose`. 도구 단계는 `tool` 필드로 `plan` 이벤트의 항목과 맞출 수 있다.
- `arrears` 결과의 할 일은 백엔드 5.10절 규칙대로 **3개**(내기 / 나눠 내기 문의 / 제도 알아보기)다. 프론트 목업(2개)과 다르니 TC1 기대값을 맞출 것.

## 에이전트 그래프와 6요소

```
preprocess → extract → validate ─(누락·판독 불가)→ need_retake
                ▲          │
                └(1회 재추출)┤
                           ├→ explain → verify_explanation ─(위반 시 1회 재생성)→ explain
                           │                     └→ compose (defer: 두 갈래가 끝난 뒤 1회)
                           └→ plan ─(지역 없음)→ ask_user(interrupt) → run_tools(병렬)
                                  └──────────────────────────────→ run_tools
                                                     evaluate ─(1회 재실행)→ run_tools
                                                         └→ compose → result
```

| 요소 | 어디서 | 코드·로그에서 보이는 곳 |
|---|---|---|
| Goal | extract, explain, compose | `read_text`·`explain`·`compose` 단계 |
| Planning | plan (필수 규칙 + LLM 플래너 병합) | `plan` 이벤트, `plan` 단계 detail (`규칙으로 추가`, `목록 밖 도구 버림`) |
| Reasoning | plan, ask_user | 상황 판단(`situation`), 지역 질문 여부 |
| Tool Use | run_tools (사칭 확인·기한·복지 병렬), explain의 lookup_terms | 도구별 `step`(tool 필드) |
| Memory | 프론트가 보내는 사용자 정보(지역·나이대) + 서버의 기관 정보 캐시(SQLite `agency_cache`) | 두 번째 요청에서 질문 생략, `cache hit` detail |
| Feedback | validate(재추출), verify_explanation(재생성), evaluate(재시도·재검색·근거 없는 경고 하향) | `validate`·`explain`·`evaluate` detail |

explain과 plan은 같은 입력(검증된 추출 결과)만 쓰므로 병렬 분기로 동시에 실행한다.

## 안전 규칙 (구현 위치)

- 숫자·날짜는 LLM 문장에 쓰지 않는다 → 자리표시자만 허용, `verify_explanation`이 코드로 검사.
- 사칭 판정·할 일 생성은 코드 규칙 (`tools/impersonation.py: decide_verdict`, `nodes/compose.py: build_todos`). LLM은 수법 근거 선택에만 관여하고, 후보 밖 id는 버린다.
- 전화 버튼은 항상 확인된 공식 번호(시드·캐시·검색), 없으면 110. 문서에 적힌 번호는 쓰지 않는다.
- 이미지: 메모리에서만. 업로드 파서도 디스크로 넘기지 않게 설정(`MultiPartParser.spool_max_size`), extract 후 상태에서 삭제, 체크포인트는 `durability="exit"` + 세션 종료 시 스레드 삭제.
- 로그: JSON 한 줄, 긴 숫자열(전화·계좌)은 끝 4자리만, URL은 경로 제거. 문서 발췌는 로그에 남기지 않는다.

## 지시서와 다르게 한 점 (근거)

1. **temperature 0**: 최신 Claude 모델(Opus 4.7 이상, Sonnet 5 이상 등)은 `temperature`를 보내면 400을 돌려준다. 그래서 받는 모델에만 0을 보내고(`app/llm/client.py: sampling_supported`), 나머지는 구조화 출력으로 일관성을 확보한다. 같은 이유로 Bedrock 구조화 출력은 강제 `tool_choice` 대신 `json_schema` 방식이 기본이다.
2. **전화번호 형식**: 8~11자리 규칙에 더해 `1355`·`110`·`182` 같은 1로 시작하는 3~4자리 특수번호를 허용한다(공공기관 대표번호).
3. **LangGraph 재개 값**: `Command(resume=None)`은 "재개 값 없음"으로 처리되어, 건너뛰기는 내부 값 `"__skip__"`으로 재개한다.

## 제출 전 사람이 해야 할 일

- [ ] `data/agencies.json`: 모든 번호·도메인을 **기관 공식 홈페이지에서 직접 확인**하고 `checkedAt` 기입. 경남 시청(김해·창원·진주·양산·거제·통영)은 번호가 비어 있다 — 확인해 채울 것.
- [ ] `data/terms.json`: 풀이 문구를 국립국어원 등 공개 순화 자료와 대조하고 `source`/`sourceUrl` 갱신.
- [ ] `data/scam_patterns.jsonl`: 수법 문장을 KISA·경찰청·금감원 자료 원문과 대조하고 항목별 `sourceUrl`을 해당 페이지로 바꾸기, 공공누리 유형 기록.
- [ ] 공공데이터포털 복지 API: 활용 신청 후 엔드포인트·요청 변수(`app/tools/welfare.py` 상단)를 명세와 대조, `scripts/fetch_welfare.py`로 `welfare_snapshot.csv`를 API 사본으로 교체.
- [ ] Bedrock 모델 접근 활성화 확인, `MODEL_*` 지정 → `scripts/eval_extract.py`로 측정표 작성.
- [ ] 실제 촬영 샘플 15~20장(`samples/`) — 지금 있는 7장은 합성 이미지(`"synthetic": true`).
- [ ] `docs/sample_run_log.json`을 실제 모델 실행 로그로 교체 (`scripts/record_run_log.py`).

## 테스트·평가

```bash
.venv/bin/python -m pytest -q                     # 단위(9.1) + 통합(9.2, fake 5개 시나리오·SSE·scripted)
.venv/bin/python scripts/make_samples.py          # 합성 샘플 다시 만들기
env -u ANTHROPIC_BASE_URL .venv/bin/python scripts/eval_extract.py   # 추출 정확도·시간 → docs/eval_extract_*.md
env -u ANTHROPIC_BASE_URL .venv/bin/python scripts/eval_e2e.py       # 전체 흐름 시간·종료 이벤트·할 일 → docs/eval_e2e_*.md
.venv/bin/python scripts/record_run_log.py --image samples/hib_arrears.jpg
.venv/bin/python scripts/build_scam_corpus.py --check
```

## 디렉터리

```
app/
  main.py, config.py, timeutil.py, logging_setup.py, textutil.py
  api/        routes_analyze.py · routes_simplify.py · routes_health.py · errors.py
  schemas/    프론트 5장 타입과 1:1 (document, explanation, agent, tools, result)
  sessions/   manager.py — 세션·이벤트 버퍼·응답 대기·만료·결과 보관·요청 수 제한
  agent/      graph.py · state.py · events.py · runner.py · scripted.py · nodes/*
  tools/      impersonation · deadline · welfare · terms · web_search
  llm/        client.py(공급자 전환) · schemas.py · fake.py · prompts/*.md
  rag/        retriever.py (BM25 + kiwipiepy)
  store/      db.py (SQLite: 기관 캐시, 복지 사본)
data/         agencies.json · terms.json · scam_patterns.jsonl · shortener_domains.txt · welfare_snapshot.csv · regions.json
scripts/      fetch_welfare · build_scam_corpus · eval_extract · make_samples · record_run_log
samples/      합성 샘플 이미지 + 정답 JSON
docs/         SOURCES.md · sample_run_log.json
```
