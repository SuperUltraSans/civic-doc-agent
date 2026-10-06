# 읽어드림 프론트엔드 (모바일 웹)

고령자가 행정문서를 찍으면 쉬운 말 설명과 **할 일 카드**를 보여 주는 화면.
`doc/읽어드림_프론트_구현지시서.md`(화면·데이터·동작)와 `doc/읽어드림_프론트_디자인지시서.md`(시각 디자인)를 기준으로 구현했다.

- 스택: Vite 8 · React 19 · TypeScript · react-router-dom 7 · CSS Modules + CSS 변수 · Phosphor Icons(Bold)
- 상태: React Context + 커스텀 훅 (외부 상태 라이브러리 없음), 저장은 `localStorage`
- 신규개발분: 이 디렉터리 전체 (2026-10-06 대회 기간 중 작성)

## 실행

```bash
cd front
npm ci
cp .env.example .env          # VITE_USE_MOCK=true 면 백엔드 없이 목업으로 동작
npm run dev                   # http://localhost:5173
```

Docker (저장소 루트에서, 백엔드와 함께):

```bash
docker compose up --build     # 루트 .env 의 FRONT_PORT (기본 3000)
```

- 컨테이너 안에서는 Vite 개발 서버가 `0.0.0.0:3000`으로 뜨고, `/api` 요청은 `API_URL`(기본 `http://back:8000`)로 프록시된다. 같은 출처라 CORS 설정이 필요 없다.
- `package.json`을 바꾼 뒤에는 `docker compose up --build -V` (익명 `node_modules` 볼륨을 새로 만든다).

### 배포 (HTTPS 엣지 하위 경로)

`front/Dockerfile.prod`가 `BASE_PATH=/civic-doc-agent/`로 빌드한 정적 파일을 nginx(`front/nginx.conf`)로 서빙한다. 실행은 루트의 `compose.prod.yaml` (루트 README 참고).

- 자산 경로: Vite `base` (`vite.config.ts`가 `BASE_PATH`를 읽음)
- 라우터: `BrowserRouter basename={import.meta.env.BASE_URL}`
- API: `VITE_API_BASE_URL`이 비어 있으면 `${BASE_URL}api/...` → `/civic-doc-agent/api/...`
- 엣지가 프리픽스를 떼고 넘기므로 컨테이너 nginx는 루트 기준으로 서빙하고, 없는 경로는 `index.html`로 돌려 새로고침해도 `/result/:docId`가 열린다.

### 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `VITE_USE_MOCK` | (없음 = 실제 백엔드) | `true`면 `src/api/mock`의 목업 API. Docker는 루트 `.env`의 `VITE_USE_MOCK`(기본 `false`) |
| `VITE_MOCK_SPEED` | `normal` | 목업 재생 속도. `normal`(단계당 0.8~2초) / `fast`(0.2초) |
| `VITE_API_BASE_URL` | (비움) | 백엔드를 다른 주소에 배포할 때만. 비우면 같은 출처의 `/api` |
| `API_URL` | `http://localhost:8000` | 개발 서버 프록시 대상 (빌드 결과에는 들어가지 않음) |
| `BASE_PATH` | `/` | 배포 경로 (빌드할 때만). 엣지 배포는 `/civic-doc-agent/` |

### 동작 모드와 시나리오

| 프론트 | 백엔드 | 쓰임 |
|---|---|---|
| `VITE_USE_MOCK=true` | 필요 없음 | 화면 개발·시연. 이미지 내용은 보지 않고 선택된 시나리오를 재생 |
| `VITE_USE_MOCK=false` | `AGENT_MODE=scripted` | 실제 SSE 연동 시험. 백엔드가 같은 시나리오를 재생 (**실제 동작 아님**) |
| `VITE_USE_MOCK=false` | `AGENT_MODE=live` | 실제 에이전트. `LLM_PROVIDER=fake`면 그래프·도구·규칙은 실제로 돌고 LLM 응답만 기록값 |

- 시나리오: `?scenario=arrears`(기본) · `blurry` · `smishing` · `local_tax` · `error`. 세션 동안 유지된다(`sessionStorage`).
- 개발 모드 또는 `?dev=1`이면 왼쪽 아래에 접힌 "개발" 상자가 보인다(시나리오 선택, 스타일 가이드 링크). 시연 녹화 때는 배포 빌드에서 쿼리로만 지정한다.
- 스타일 가이드: `/dev/styleguide` (개발 모드 또는 `?dev=1`에서만).

## 테스트

```bash
npm test           # 단위 테스트 (vitest): 금액·날짜 표기, 문장 채우기, 달력 파일, SSE 파서, 기록 저장, 할 일 정렬
npm run typecheck  # 타입 검사
npm run build      # 배포 빌드 (dist/)
```

### 테스트 케이스 결과 (구현지시서 10장)

2026-10-06, Playwright(헤드리스 Chromium) 390×844로 자동 수행. 네 가지 연결 방식에서 모두 같은 결과였다.
① 목업(`VITE_USE_MOCK=true`) ② Docker 백엔드 `AGENT_MODE=scripted` ③ 로컬 백엔드 `AGENT_MODE=live` + `LLM_PROVIDER=fake` (실제 LangGraph 그래프·interrupt·도구 실행)
④ 배포 주소 `https://kimanyfootcleaner.asuscomm.com/civic-doc-agent/` (HTTPS 엣지 경유, 배포 빌드, `AGENT_MODE=scripted`). SSE 단계 이벤트가 엣지에서 모이지 않고 1~2초 간격으로 도착하는 것도 확인했다.

| ID | 확인한 것 | 결과 |
|---|---|---|
| TC1 | 단계 표시 → 지역 질문 → 결과: 요약(3만 2,500원), 할 일 3개, 복지 3건, 사칭 확인 한 줄, 형광펜 3곳 이하 | 통과 |
| TC2 | `blurry`: 다시 찍기 안내 + 팁 3개, "다시 찍기"가 파일 선택(카메라)을 엶 | 통과 |
| TC3 | `smishing`: 경고 카드가 할 일보다 위, 전화 버튼 `tel:15771000`(공식 번호), 납부 할 일 없음 | 통과 |
| TC4 | 질문에서 건너뛰기 → "사는 지역을 알려 주시면…" 안내 | 통과 |
| TC5 | 지역 답변 후 같은 시나리오 재실행 → 질문 없이 결과 | 통과 |
| TC6 | "했어요" → 홈 개수 3→2, 새로고침 후 유지, "아직 안 했어요"로 되돌림 | 통과 |
| TC7 | "더 쉽게 설명해 주세요" → level 2 문장으로 교체, 버튼 사라짐, 숫자 그대로 | 통과 |
| TC8 | `error` → 오류 안내, "다시 해 보기"가 같은 이미지로 `POST /api/analyze` 재요청 | 통과 (목업은 요청 없음) |
| TC9 | 360·390px × 보통·크게·아주 크게, 전 화면 가로 스크롤 없음 | 통과 (자동 측정, 44장) |
| TC10 | `format.ts` 8.1절 표의 모든 예시 | 통과 (`npm test`) |

함께 확인: 결과 새로고침 시 기록에서 복원, 기록에 문서 연락처·주소·`checkedValue` 없음, 저장소에 이미지 없음, 달력 `.ics` 내려받기, 가족에게 보내기(복사) 문장에 문서 번호 없음, `/processing` 직접 진입 시 홈으로.

**아직 하지 않은 것** (실기기 필요): iOS Safari·안드로이드 Chrome에서 촬영 회전, `.ics` 열기, 공유 시트, 읽어주기(한국어 음성) 확인. 고령자 3명 이상 사용 기록(디자인 지시서 9.4절).

## 디렉터리

```
src/
  api/        types.ts(데이터 계약) · index.ts(목업/실제 선택) · http/(fetch+SSE) · mock/(시나리오 재생)
  context/    Settings · Profile · Todo · History · Capture(이미지, 메모리 전용)
  hooks/      useLocalStorage · useSpeech · useShare · usePhotoPicker · usePageHeading
  lib/        format · template · image · ics · history · todos · scenario · regions · agency · korean
  components/ TopBar · BigButton · Highlight · Card · StepList · SpeakButton · Collapsible · TodoCard
              ActionButton · Toast · Cutline · ImpersonationNotice · ConfirmDialog · Page
  pages/      Home · Capture · Processing(진행·질문·다시 찍기·오류) · Result · Todos · Settings
  styles/     tokens.css(디자인 토큰) · global.css
  dev/        ScenarioSwitcher · StyleguidePage
```

## 디자인 결정 (디자인 지시서 9.1절 2번)

홈 화면: 상단 바 왼쪽에 함렛체 "읽어드림", 흰 종이 첫 줄에 한 줄 설명이 있고, 바로 아래 잉크색 큰 버튼(높이 7rem, 카메라 아이콘 위·글자 아래, 검은 단이 받쳐 누를 수 있는 도장처럼 보임)이 화면에서 가장 큰 요소다. 그 아래 흰 바탕 테두리 버튼 "사진첩에서 고르기", 간격을 넓게 두고 할 일 요약 카드, 맨 아래 밑줄 링크 "설정". 색은 잉크·흰색뿐이고 노란 형광펜은 3일 이내 기한에만 나타난다.

이 문서가 없었다면 골랐을 기본값과 대체한 것:

1. 파란 주요 버튼 + 흐린 그림자 카드 → 잉크 바탕 버튼 + 흐림 없는 아래 단, 그림자 없는 얇은 테두리 카드
2. Pretendard/Noto Sans KR 한 글꼴 → 제목·요약은 Hahmlet, 본문·숫자는 IBM Plex Sans KR(`tabular-nums`)
3. 숫자를 굵은 글씨·색으로 강조, 로딩 스피너 → 금액·기한에만 형광펜(진입 시 한 번 그어짐), 종이 서식 체크 칸 모양의 단계 목록

## 지시서와 다르게 한 점 (근거)

1. **`arrears` 목업의 할 일이 3개**: 구현지시서 6.2절은 2개(내기, 나눠 내기 문의)지만, 백엔드 지시서 5.10절 규칙은 복지 결과가 있으면 "도움 받을 수 있는 제도 알아보기"를 더한다. "목업이어도 데이터 흐름은 실제와 같아야 한다"(구현지시서 머리말)에 따라 목업도 백엔드와 같은 3개로 맞췄다. TC1 기대값을 "할 일 2개 이상"으로 읽는다.
2. **목업 사칭 문자의 주소**: 구현지시서 6.1절대로 가짜 주소는 `.example` 도메인(`http://short.example/...`)을 쓴다. 화면에는 표시되지 않는다.
3. **SSE 수신은 `EventSource` 대신 `fetch` 스트림**: `EventSource`는 끊기면 자동으로 다시 연결하는데, 백엔드는 재연결 시 버퍼를 처음부터 다시 보내 단계가 중복된다. `fetch`로 받아 끊김을 직접 오류 화면(`network`)으로 넘긴다. 45초 동안 아무것도 오지 않아도 끊긴 것으로 본다(백엔드는 15초마다 ping).
4. **`unsupported_image` 오류**: 같은 사진으로 다시 해도 소용없으므로 "다시 해 보기" 대신 "다시 찍기"를 보여 준다.
5. **질문 대기 중 서버가 건너뛰고 진행**(3분 초과)하면 단계 이벤트를 받는 즉시 진행 화면으로 돌아간다.
6. **"그 밖의 지역"을 고르면 `기타`로 저장**해 다음에 다시 묻지 않는다(질문 1회 원칙). 백엔드는 `기타`를 지역 없음으로 처리한다.
7. 사칭 확인 결과가 **주소만 있는 문서**일 때는 "번호" 대신 "주소" 문구를 쓴다. 이를 위해 기록에는 "번호가 있었는지 / 주소가 있었는지"만 남긴다(값은 저장하지 않음).
8. **홈 화면 제목 위치** (디자인 지시서 6.1절): 지시서는 상단 바(뒤로 없음) 아래 본문 첫 줄에 "읽어드림"을 두지만, 홈에는 "뒤로"가 없어 상단 바 왼쪽이 비어 보인다는 피드백(2026-10-06)에 따라 **홈에서는 제목을 상단 바 왼쪽에** 둔다. 화면 제목(h1)·포커스 이동은 그대로이고, 다른 화면은 그 자리에 "뒤로"가 있다.
9. **움직임** (디자인 지시서 7장): 지시서는 결과 화면의 형광펜 긋기만 장식 모션으로 두고 화면 전환 애니메이션을 금지하지만, "버튼·화면 전환이 부드러웠으면 좋겠다"는 피드백(2026-10-06)에 따라 짧고 차분한 움직임을 더했다. 튀거나 흔들리는 효과는 쓰지 않고, 휴대폰의 "동작 줄이기" 설정이면 모두 끈다.
   - 화면 전환: 본문만 살짝 올라오며 나타남 0.22초(상단 바는 고정). 처리 중 화면의 진행·질문·다시 찍기·오류 전환도 같게
   - 버튼: 주요 버튼은 아래 단만큼 눌림, 보조·실행·완료 버튼은 살짝 내려가며 바탕이 옅게 물듦(0.11초). 상단 바·설정 선택 칸·홈 할 일 카드도 누를 때 바탕이 바뀜
   - 접기: 화살표가 돌아가고 내용이 펼쳐짐(`::details-content` 를 지원하는 브라우저만, 아니면 바로 열림)
   - 단계 목록의 새 단계, 알림, 확인 창, 촬영 미리보기가 살짝 나타남. 끝낸 일로 바뀌는 카드는 색이 부드럽게 바뀜
   - 함께 고친 것: 화면을 넘기면 맨 위부터 보인다(이전 화면의 스크롤 위치가 남던 문제)
10. **끝낸 일 지우기** (구현지시서 8.6절에 없던 기능, 2026-10-06 요청): 끝낸 일 카드에 "지우기", 할 일 목록의 "끝낸 일" 묶음 아래에 "끝낸 일 모두 지우기"를 둔다. 아직 안 한 일은 지울 수 없다. "했어요"와 같이 확인 창 대신 **되돌리기 알림(5초)**을 띄운다(확인 창은 "모든 기록 지우기"에만, 8.7절). 지운 할 일은 결과 화면에서도 다시 나타나지 않는다(모두 지웠으면 "이 문서의 할 일은 모두 끝내고 지웠어요"). 할 일을 모두 끝내 미완료가 없으면 홈에 "해야 할 일을 모두 끝냈어요" + "끝낸 일 N개 보기"(할 일 화면을 끝낸 일 묶음이 펼쳐진 채로 연다)를 둔다 — 지시서 8.2절은 미완료가 있을 때만 요약 카드를 두어, 모두 끝내면 끝낸 일 목록으로 갈 길이 없었다.
11. `crypto.randomUUID`는 HTTPS에서만 쓸 수 있어, 휴대폰으로 같은 네트워크의 http 주소에 접속해도 동작하도록 `getRandomValues`로 id를 만든다.

## 출처·라이선스

| 이름 | 버전 | 라이선스 | 용도 |
|---|---|---|---|
| React / React DOM | 19.3.0 | MIT | 화면 |
| react-router-dom | 7.18.4 | MIT | 라우팅 |
| @phosphor-icons/react (Phosphor Icons) | 2.1.10 | MIT | 아이콘 (Bold) |
| Vite / @vitejs/plugin-react | 8.3.2 / 6.1.2 | MIT | 빌드·개발 서버 |
| TypeScript | 7.0.2 | Apache-2.0 | 타입 |
| Vitest | 4.1.11 | MIT | 단위 테스트 |
| @types/node | 22.20.5 | MIT | 빌드 설정 타입 |
| Hahmlet (함렛) | Google Fonts | SIL Open Font License 1.1 | 제목·요약 글꼴 |
| IBM Plex Sans KR | Google Fonts | SIL Open Font License 1.1 | 본문·버튼·숫자 글꼴 |

- 글꼴은 Google Fonts에서 불러온다(`index.html`, `display=swap`). 파일은 저장소에 넣지 않는다.
- 목업 데이터의 이름·번호·주소는 모두 가상값이다. 공식 대표번호(국민건강보험공단 1577-1000)와 공식 대표 페이지 주소만 실제 값을 쓴다.
