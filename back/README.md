# 읽어드림 백엔드 (에이전트 API)

고령자가 찍은 행정문서를 읽고, 쉬운 말 설명 + 사칭 확인·기한 정리·복지 연계를 판단해 **할 일 카드**로 정리하는 에이전트 API.
`읽어드림_백엔드_구현지시서.md` 기준으로 구현했고, 응답 JSON은 `읽어드림_프론트_구현지시서.md` 5장 타입과 같다(camelCase).

- 스택: Python 3.12(로컬 3.14에서도 테스트) · FastAPI · LangGraph · openai SDK · google-genai SDK · SQLite · BM25(kiwipiepy)
- LLM은 **역할마다 다른 공급자**를 쓴다 (팀 결정, 2026-10-06). **AWS(Bedrock)는 쓰지 않기로 해서 구현에서 뺐다** (지시서 1장·7.1절의 `bedrock` 공급자).

  | 역할 | 쓰는 노드 | 모델 | 공급자·API |
  |---|---|---|---|
  | 문서 읽기 `vision` | extract (이미지 입력) | Gemini 3.8 Flash `gemini-3.8-flash` | Google Gemini API, generateContent + JSON 스키마 |
  | 계획 `reason` | plan | GPT-6.1 Sol `gpt-6.1-sol` | OpenAI Responses API, `responses.parse` (strict JSON 스키마) |
  | 빠른 `fast` | explain, 복지 재정렬, 수법 선택 | GPT-6 Luna `gpt-6-luna` | OpenAI Responses API |
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
docker compose up --build         # 저장소 루트의 docker-compose.yml (기본 back: 127.0.0.1:8000, front: 127.0.0.1:3000 — 루트 .env 로 변경)
```

> 루트 compose는 `./back`을 컨테이너 `/app`에 마운트하므로 `back/.env`가 그대로 읽힌다. 루트 `.env`(compose `env_file`)에 넣어도 된다.
>
> 세션·SSE 버퍼가 프로세스 메모리에 있으므로 **워커는 1개**로 둔다 (Dockerfile 기본값).

### 동작 모드

| 설정 | 용도 |
|---|---|
| `AGENT_MODE=scripted` | 프론트 목업과 같은 시나리오 키(`arrears`, `blurry`, `smishing`, `local_tax`, `error`)의 이벤트를 **재생**. LLM 없이 실제 SSE 연동 시험용. `POST /api/analyze`의 `scenario` 폼 필드로 고른다. **실제 동작이 아님** — 제출 문서에서 구분해 적을 것 |
| `AGENT_MODE=live` + `LLM_PROVIDER=fake` | 실제 그래프·도구·규칙이 돌고, LLM 응답만 시나리오별 기록값(`app/llm/fake.py`). 통합 테스트용 |
| `AGENT_MODE=live` (기본 구성) | 실제 동작. 역할별 공급자·모델은 아래 표 |

LLM 설정 (`app/llm/client.py`가 역할 → 공급자 클라이언트로 넘긴다. 노드 코드는 공급자를 모른다):

| 변수 | 기본 구성 | 설명 |
|---|---|---|
| `LLM_PROVIDER` | `openai` | 기본 공급자 `openai` · `google` · `anthropic` · `fake`. **`fake`면 역할별 설정과 관계없이 모두 기록된 응답** |
| `PROVIDER_VISION` / `PROVIDER_REASON` / `PROVIDER_FAST` | `google` / (비움) / (비움) | 역할별 공급자. 비우면 `LLM_PROVIDER` |
| `MODEL_VISION` / `MODEL_REASON` / `MODEL_FAST` | `gemini-3.8-flash` / `gpt-6.1-sol` / `gpt-6-luna` | 모델 ID는 코드에 쓰지 않는다. 한 역할이 비면 다른 역할의 **(공급자, 모델)을 함께** 빌려 쓴다 |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | (비움) | 쓰는 공급자의 키만 있으면 된다. 비어 있으면 설정 오류(`server`)로 끝나고 로그에 어떤 키인지 남는다 |
| `LLM_EFFORT`, `EFFORT_VISION/REASON/FAST` | (비움 = 공급자 기본값) | 사고 수준. google `thinking_level`: low·medium·high (3.8 Flash는 minimal 불가), openai `reasoning.effort`: none(Luna만)·low·medium·high… |
| `LLM_MAX_TOKENS` | `8000` | 사고(thinking/reasoning) 토큰도 포함된다. 너무 낮으면 출력이 잘려 형식 오류로 처리된다 |
| `GEMINI_MEDIA_RESOLUTION` | (비움 = high, 이미지당 1,120토큰) | `low`·`medium`(560)·`high`·`ultra_high`(2,240). 2026-10-06 고지서 3장 비교: 기본 15/15·5.2초, medium 15/15·4.5초·입력 토큰 −30%, ultra_high 14/15·5.2초 |
| `LLM_OPENAI_BASE_URL` / `LLM_GEMINI_BASE_URL` | 공식 주소 | SDK가 `OPENAI_BASE_URL` 같은 환경 변수(예: 다른 도구가 설정한 프록시)를 따라가 키가 엉뚱한 주소로 가지 않게 고정. Gemini는 `vertexai=False`로 고정 |
| `ANTHROPIC_API_KEY`, `LLM_ANTHROPIC_BASE_URL`, `LLM_REFUSAL_FALLBACK` | — | 선택 공급자 `anthropic`용 (기본 구성에서는 쓰지 않음) |

- 개인정보: OpenAI 호출은 `store=False`로 보내 응답을 OpenAI 쪽에 저장하지 않는다. Gemini API는 **유료 등급**에서만 입력이 모델 개선에 쓰이지 않으므로(약관 확인) 유료 키를 쓴다.

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
- 단계 id: `read_text`, `classify`, `validate`, `explain`(tool `lookup_terms`), `plan`, `impersonation`, `deadline`, `welfare`, `evaluate`, `review`, `impersonation_more`·`welfare_more`(결과 검토 후 추가 도구), `compose`. 도구 단계는 `tool` 필드로 `plan` 이벤트의 항목과 맞출 수 있다.
- `arrears` 결과의 할 일은 백엔드 5.10절 규칙대로 **3개**(내기 / 나눠 내기 문의 / 제도 알아보기)다. 프론트 목업도 같은 3개로 맞췄다(TC1 기대값은 "2개 이상"으로 읽는다).
- 프론트는 SSE를 `EventSource`가 아니라 `fetch` 스트림으로 받는다(자동 재연결 시 버퍼가 처음부터 다시 와 단계가 중복되는 것을 막기 위해). 45초 동안 아무 바이트도 없으면 끊긴 것으로 본다.

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
                                                         └→ review (LLM이 도구 결과를 보고 판단, 1회)
                                                              ├(추가 도구)→ run_followups(병렬) → evaluate
                                                              └→ compose → result
```

**결과 검토(review)**: 도구 실행과 코드 점검이 끝나면 계획 모델(GPT-6.1 Sol)이 도구 결과를 보고 추가 도구를 최대 2개 고른다. 한 번만 하고 질문은 하지 않는다.

| 추가 도구 | 언제 | 하는 일 (단계 id) |
|---|---|---|
| `find_official_contact` | 사칭 확인에서 공식 번호를 못 찾았을 때 | LLM이 제안한 기관 이름(예: "종로구청")으로 공식 번호를 다시 찾고 사칭 확인을 다시 한다 (`impersonation_more`). 찾았을 때만 결과를 바꾼다 |
| `search_welfare` | 복지 결과가 없거나 맞지 않을 때, 또는 계획에 없었지만 필요해 보일 때 | LLM이 정한 검색어로 복지 제도를 더 찾아 처음 결과와 합친다 (`welfare_more`) |

- LLM은 "무엇을 왜 더 할지"만 정한다. 번호는 여전히 시드 표·캐시·`.go.kr` 검색(기관명 확인)으로만 정해지고, 사칭 판정·할 일은 코드 규칙이 정한다.
- 목록 밖 도구, 지금 필요 없는 도구, 이미 찾아본 기관 이름, 형식이 이상한 이름·검색어는 코드가 버리고 `review` 단계 detail에 남긴다 (`버림: …`). 숫자가 섞인 이유는 규칙 문장으로 바꾼다.
- 추가 실행한 도구는 결과의 `plan`에 `결과를 보고 추가: …` 이유로 붙는다 (화면 "확인 과정 보기"에서 "결과를 보고 에이전트가 더한 확인"으로 표시).

| 요소 | 어디서 | 코드·로그에서 보이는 곳 |
|---|---|---|
| Goal | extract, explain, compose | `read_text`·`explain`·`compose` 단계 |
| Planning | plan (필수 규칙 + LLM 플래너 병합) | `plan` 이벤트, `plan` 단계 detail (`규칙으로 추가`, `목록 밖 도구 버림`) |
| Reasoning | plan, ask_user, **review** | 상황 판단(`situation`), 지역 질문 여부, 도구 결과를 본 판단(`review` 단계 detail의 `판단:`) |
| Tool Use | run_tools (사칭 확인·기한·복지 병렬), **run_followups** (LLM이 결과를 보고 고른 추가 도구), explain의 lookup_terms | 도구별 `step`(tool 필드), `impersonation_more`·`welfare_more` 단계, plan의 `결과를 보고 추가` |
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

1. **temperature 0**: OpenAI 추론 모델(GPT-5 이후, GPT-6.1 Sol·GPT-6 Luna 포함)은 `temperature`를 받지 않고, Gemini 3 계열은 기본값(1.0)에서 바꾸지 말라는 것이 공식 권고(바꾸면 반복·품질 저하)다. 그래서 받는(권고되는) 모델에만 0을 보내고(`app/llm/providers/*: sampling_supported`), 나머지는 구조화 출력(JSON 스키마)과 코드 검사(validate·verify_explanation)로 일관성을 확보한다.
1-2. **사칭 판정 — 공식 도메인의 http 주소** (5.7절 보완): 지시서는 `http://`를 주소 검사 위반으로 보고, "공식 번호와 다름 + 주소 위반"이면 `mismatch`다. 그런데 종이 고지서는 공식 주소(`.go.kr`·공식 목록)를 http로 적는 일이 흔하고, 적힌 번호는 부서 번호라 대표번호와 다르기 쉽다. 그래서 진짜 구청 고지서가 '사칭 의심'으로 뒤집혔다(실제 키 시험에서 확인한 구조, NAVER 검색으로 대표번호를 찾으면 발생). **공식 도메인 주소의 http만으로는 위험 신호로 세지 않는다** → `unknown`(대표번호로 확인 안내). 경고 문구 "보호되지 않는 주소(http)예요"는 그대로 보여 준다. 비공식 도메인의 http, 단축 주소, 휴대전화 번호, 수법 근거는 그대로 `mismatch` 사유다.
1-5. **결과 검토 단계 추가** (4.1절 그래프 보완): 지시서 그래프는 `evaluate → compose`이고 evaluate는 코드 점검만 한다. LLM이 도구 결과를 보고 다음 도구를 정하는 단계가 없어 도구 사용이 사실상 코드에 고정돼 보였으므로, `evaluate` 뒤에 `review`(LLM 판단 1회) → `run_followups`(추가 도구) → `evaluate`를 넣었다. 판정·할 일은 여전히 코드 규칙이다.
1-6. **종이 고지서의 수법 검사 조건** (5.7절 보완): 사칭 수법 검사(RAG + LLM 선택)는 사칭 의심 문자에는 항상, 종이 고지서·안내문에는 휴대전화 번호·비공식/단축/유사 주소 같은 **구체적 위험 신호가 있을 때만** 한다. 실제 키 시험에서 진짜 구청 과태료 고지서에 "과태료 미납을 핑계로 링크 접속 유도" 수법이 골라졌고, 공식 번호를 찾으면(결과 검토의 `find_official_contact`) 부서 번호와 달라 '사칭 의심'으로 뒤집히는 경로였다.
1-7. **기간 밖 기한 = 오래된 문서일 수 있음** (5.3절 보완): 지시서는 기한이 오늘 기준 −365일 ~ +180일을 벗어나면 문제로 보고, 재추출 후에도 그러면 필수 값 누락 → "글씨가 잘 안 보여요"로 끝낸다. 모바일 실사용에서 옛 고지서(2019·2023년)를 찍으니 사진은 잘 읽혔는데도 매번 다시 찍기만 반복됐다. 이제 날짜 형식은 맞고 기간만 벗어나면 **앞서 읽은 값을 보여 주지 않고 다시 읽게 해서, 두 번 같은 날짜면 실제 날짜로 인정**한다(화면은 "N일 지났어요"로 표시). 두 번 값이 다르면 지금처럼 다시 찍기 안내를 하고, 팁에 "날짜가 적힌 부분이 잘 보이게 찍어 주세요"를 붙인다. 연도를 잘못 읽는 실수를 잡으려는 원래 목적은 '두 번 독립적으로 같은 값' 조건으로 유지한다.
1-8. **사진 품질 사전 점검** (5.1절 보완): 지시서의 preprocess는 회전·축소만 하고 읽을 수 있는지는 모델(`legible`)이 판단한다. 흐린 사진도 모델 호출(4~6초)을 거친 뒤에야 다시 찍기가 나오므로, 크기(긴 변 500px 미만)·밝기(평균 30 미만, 또는 248 초과이면서 명암 차이 없음)·명암(표준편차 6 미만)·선명도(라플라시안 분산 10 미만)가 **명백히** 나쁘면 모델 호출 없이 바로 다시 찍기를 안내한다(단계 id `photo_check`, 문제별 메시지·팁). 기준은 샘플·실사진·인위적 변형으로 측정해 보수적으로 잡았고(읽을 수 있던 실사진은 선명도 196 이상), 모든 사진의 측정값을 서버 로그(`photo check`)에 남긴다. `PHOTO_CHECK_ENABLED=false`로 끈다.
1-9. **JPEG 다시 저장 생략**: 프론트가 이미 1500px JPEG로 줄여 보낸 사진은 서버가 다시 저장하지 않는다(화질 손실·시간 절약). 단 EXIF·XMP 등 메타데이터나 회전 정보가 있으면 반드시 다시 저장해 지운다 — 촬영 위치(GPS)가 LLM 공급자로 넘어가지 않게.
1-3. **계획 문장의 숫자** (0장 3번 보완): 계획(plan)의 `situation`·`reason`은 "확인 과정 보기"에 그대로 보이므로, 금액·날짜·번호가 들어 있으면 코드가 규칙 문장(숫자 없음)으로 바꾼다 (`textutil.numeric_issue`, 설명 검사와 같은 규칙). 계획 모델은 오늘 날짜를 모르므로 기한 경과는 판단하지 않게 지시했다 (`prompts/plan.md` 1.1).
1-4. **실시간 검색 기관 이름**: "서울특별시 종로구청장"처럼 직위가 붙은 발신 기관은 직위를 뗀 이름("서울특별시 종로구")으로 검색한다. 검색 결과 페이지에 기관 이름이 있어야 번호를 채택하기 때문이다.
1-1. **LLM 공급자**: 지시서 7.1절은 `bedrock`(기본) / `anthropic`이지만, 팀 결정으로 AWS를 빼고 역할별로 Google Gemini(문서 읽기)·OpenAI(계획·빠른)를 쓴다. 모델 ID·키는 여전히 환경 변수로만 받는다.
2. **전화번호 형식**: 8~11자리 규칙에 더해 `1355`·`110`·`182` 같은 1로 시작하는 3~4자리 특수번호를 허용한다(공공기관 대표번호).
3. **LangGraph 재개 값**: `Command(resume=None)`은 "재개 값 없음"으로 처리되어, 건너뛰기는 내부 값 `"__skip__"`으로 재개한다.
4. **할 일의 전화 버튼 대체 규칙** (5.10절 보완): 문서에 연락처가 없어 사칭 확인을 하지 않았으면, 발신 기관의 **시드 표 번호**로 전화 버튼을 만든다(문서 번호는 여전히 쓰지 않음). "나눠서 낼 수 있는지 물어보기"는 물어볼 곳이 꼭 있어야 하므로 공식 번호가 없으면 정부민원안내콜센터(110)로 안내한다.

## 제출 전 사람이 해야 할 일

> 전체 목록(LLM·키·데이터 확인·평가 자료)은 저장소 루트 [`사용자_확인_필요_목록.md`](../사용자_확인_필요_목록.md)에 정리했다.

- [ ] `data/agencies.json`: 모든 번호·도메인을 **기관 공식 홈페이지에서 직접 확인**하고 `checkedAt` 기입. 경남 시청(김해·창원·진주·양산·거제·통영)은 번호가 비어 있다 — 확인해 채울 것.
- [ ] `data/terms.json`: 풀이 문구를 국립국어원 등 공개 순화 자료와 대조하고 `source`/`sourceUrl` 갱신.
- [ ] `data/scam_patterns.jsonl`: 수법 문장을 KISA·경찰청·금감원 자료 원문과 대조하고 항목별 `sourceUrl`을 해당 페이지로 바꾸기, 공공누리 유형 기록.
- [ ] 공공데이터포털 복지 API: 활용 신청 후 엔드포인트·요청 변수(`app/tools/welfare.py` 상단)를 명세와 대조, `scripts/fetch_welfare.py`로 `welfare_snapshot.csv`를 API 사본으로 교체.
- [ ] `OPENAI_API_KEY`·`GEMINI_API_KEY` 입력, `AGENT_MODE=live` → `scripts/eval_extract.py`로 측정표 작성 (사고 수준 `EFFORT_*` 조정 포함).
- [ ] 실제 촬영 샘플 15~20장(`samples/`) — 지금 있는 7장은 합성 이미지(`"synthetic": true`).
- [ ] `docs/sample_run_log.json`을 실제 모델 실행 로그로 교체 (`scripts/record_run_log.py`).

## 테스트·평가

```bash
.venv/bin/python -m pytest -q                     # 단위(9.1) + 통합(9.2, fake 5개 시나리오·SSE·scripted)
.venv/bin/python scripts/make_samples.py          # 합성 샘플 다시 만들기
env -u OPENAI_BASE_URL .venv/bin/python scripts/eval_extract.py   # 추출 정확도·시간 → docs/eval_extract_*.md
env -u OPENAI_BASE_URL .venv/bin/python scripts/eval_e2e.py       # 전체 흐름 시간·종료 이벤트·할 일 → docs/eval_e2e_*.md
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
  llm/        client.py(역할별 공급자 라우팅·재시도) · base.py · providers/(openai·gemini·anthropic) · schemas.py · fake.py · prompts/*.md
  rag/        retriever.py (BM25 + kiwipiepy)
  store/      db.py (SQLite: 기관 캐시, 복지 사본)
data/         agencies.json · terms.json · scam_patterns.jsonl · shortener_domains.txt · welfare_snapshot.csv · regions.json
scripts/      fetch_welfare · build_scam_corpus · eval_extract · make_samples · record_run_log
samples/      합성 샘플 이미지 + 정답 JSON
docs/         SOURCES.md · sample_run_log.json
```
