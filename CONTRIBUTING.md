# Contributing

## 커밋 메시지 규칙

[Conventional Commits](https://www.conventionalcommits.org/ko/v1.0.0/)를 기반으로 합니다.

### 형식

```
<type>(<scope>): <제목>

<본문 (선택): 무엇을, 왜 바꿨는지>
```

- **type**: 영어 소문자, 아래 목록 중 하나
- **scope** (선택): `back`, `front`, `docker`, `docs`
- **제목**: 한국어, 50자 이내, 마침표 없이 명사형으로 끝맺기 (`~ 추가`, `~ 수정`)

### type

| type | 용도 | 예시 |
|---|---|---|
| `feat` | 새 기능 | `feat(back): 고지서 OCR 텍스트 추출 API 추가` |
| `fix` | 버그 수정 | `fix(front): 업로드 후 미리보기 안 뜨는 문제 수정` |
| `refactor` | 동작 변화 없는 구조 개선 | `refactor(back): LLM 호출부 서비스 레이어로 분리` |
| `style` | 포맷팅 등 동작과 무관한 변경 | `style(front): prettier 적용` |
| `docs` | 문서 | `docs: API 명세 초안 추가` |
| `test` | 테스트 추가·수정 | `test(back): 사칭 판별 로직 테스트 추가` |
| `chore` | 설정, 빌드, 의존성 | `chore(docker): 백엔드 FastAPI로 CMD 교체` |

### 이슈 연결

관련 이슈가 있으면 제목 끝이나 본문에 번호를 적습니다. GitHub에서 자동으로 연결됩니다.

```
feat(back): 납부 기한 알림 API 추가 (#12)
```

PR 본문에 `Closes #12`를 적으면 머지될 때 이슈가 자동으로 닫힙니다.

## Pull Request

- PR 제목도 커밋 메시지와 같은 형식으로 작성합니다. Squash merge 시 PR 제목이 그대로 커밋 제목이 됩니다.
