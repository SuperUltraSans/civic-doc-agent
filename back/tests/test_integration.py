"""통합 테스트 (지시서 9.2절).

LLM_PROVIDER=fake 로 그래프 전체를 프론트와 같은 5개 시나리오로 실행하고,
POST /analyze → GET /events(SSE) → POST /answer → result 까지 이벤트 순서와 응답 스키마(camelCase)를 확인한다.
"""

from __future__ import annotations

import pytest

from app.schemas.agent import AgentStep, InfoQuestion, PlanItem, RetakeRequest
from app.schemas.result import AnalysisResult
from tests.conftest import jpeg_bytes, run_session

TERMINAL = {"need_retake", "result", "error"}

RESULT_KEYS = {"docId", "document", "explanation", "plan", "tools", "todos", "steps", "createdAt"}


def names(events):
    return [n for n, _ in events]


def assert_contract(events):
    """모든 이벤트가 프론트 5장 타입과 같은 모양인지, 종료 이벤트는 마지막에 하나인지."""
    assert names(events)[-1] in TERMINAL
    assert sum(1 for n in names(events) if n in TERMINAL) == 1
    for name, data in events:
        if name == "step":
            AgentStep.model_validate(data)
            assert "done_label" not in data
        elif name == "plan":
            [PlanItem.model_validate(p) for p in data]
        elif name == "need_info":
            InfoQuestion.model_validate(data)
            assert len(data["options"]) <= 7
        elif name == "need_retake":
            RetakeRequest.model_validate(data)
        elif name == "result":
            assert set(data) == RESULT_KEYS
            AnalysisResult.model_validate(data)
            # camelCase 키만
            for key in ("docTypeLabel",):
                assert key in data["document"]
            assert "summaryTemplate" in data["explanation"]


def step_status(events, step_id):
    return [d["status"] for n, d in events if n == "step" and d["id"] == step_id]


async def test_arrears_full_flow(client):
    events = await run_session(client, "arrears", answer="김해시")
    assert_contract(events)
    seq = names(events)
    assert seq.index("plan") < seq.index("need_info") < seq.index("result")
    assert step_status(events, "read_text") == ["running", "done"]
    assert step_status(events, "impersonation") == ["running", "done"]
    # Feedback: 체납액 신뢰도 낮음 → 재확인, 설명 숫자 노출 → 1회 재생성
    validate = [d for n, d in events if n == "step" and d["id"] == "validate" and d["status"] == "done"][0]
    assert "arrears 재확인" in validate["detail"]
    result = events[-1][1]
    explain = [s for s in result["steps"] if s["id"] == "explain"][0]
    assert "재생성" in explain["detail"]
    assert "32,500" not in result["explanation"]["summaryTemplate"]
    # TC1: 요약·할 일·복지 2건 이상·사칭 확인
    assert result["tools"]["impersonation"]["status"] == "match"
    assert [p["tool"] for p in result["plan"]] == ["check_impersonation", "manage_deadline", "search_welfare"]
    welfare = result["tools"]["welfare"]
    assert len(welfare["items"]) >= 2 and welfare["usedProfile"] is True
    assert welfare["items"][-1]["name"].startswith("복지멤버십")
    assert all(set(i) == {"name", "summary", "reason", "url"} for i in welfare["items"])  # 내부 키 제거
    assert [t["title"] for t in result["todos"]][:2] == ["건강보험료 내기", "나눠서 낼 수 있는지 물어보기"]
    assert {s["id"] for s in result["steps"]} >= {"read_text", "classify", "validate", "explain", "plan", "impersonation", "deadline", "welfare", "evaluate", "compose"}


async def test_arrears_skip_question(client):
    """TC4: 질문 건너뛰기 → 결과 정상, usedProfile=false."""
    events = await run_session(client, "arrears", answer=None)
    assert_contract(events)
    assert events[-1][1]["tools"]["welfare"]["usedProfile"] is False


async def test_arrears_with_saved_region_asks_nothing(client):
    """TC5: 프로필에 지역이 있으면 질문 없이 진행 (Memory)."""
    events = await run_session(client, "arrears", profile={"region": "창원시", "ageGroup": "70s"})
    assert_contract(events)
    assert "need_info" not in names(events)
    assert events[-1][1]["tools"]["welfare"]["usedProfile"] is True


async def test_blurry_retake(client):
    events = await run_session(client, "blurry")
    assert_contract(events)
    assert names(events)[-1] == "need_retake"
    assert events[-1][1]["message"] == "글씨가 잘 안 보여요"
    assert "plan" not in names(events)


async def test_smishing_mismatch(client):
    events = await run_session(client, "smishing")
    assert_contract(events)
    result = events[-1][1]
    imp = result["tools"]["impersonation"]
    assert imp["status"] == "mismatch"
    assert imp["officialPhone"] == "1577-1000"
    assert "짧게 줄인 인터넷 주소가 있어요" in imp["redFlags"]
    assert [t["title"] for t in result["todos"]] == ["공식 번호로 진짜인지 확인하기"]
    assert "deadline" not in result["tools"]
    assert "need_info" not in names(events)


async def test_local_tax_no_question_no_welfare(client):
    events = await run_session(client, "local_tax", profile={"region": "김해시"})
    assert_contract(events)
    result = events[-1][1]
    assert [p["tool"] for p in result["plan"]] == ["manage_deadline"]
    assert "welfare" not in result["tools"]
    assert "need_info" not in names(events)
    assert [t["title"] for t in result["todos"]] == ["지방세 내기"]


async def test_error_event(client):
    events = await run_session(client, "error")
    assert_contract(events)
    assert events[-1] == ("error", {"code": "network", "message": "연결이 잠시 끊겼어요"})


async def test_events_replay_from_buffer(client):
    """종료 후 다시 연결해도 버퍼의 이벤트를 처음부터 받는다."""
    from app.sessions.manager import get_manager

    events = await run_session(client, "local_tax", profile={"region": "김해시"})
    sid = next(iter(get_manager().sessions))
    for s in get_manager().sessions.values():
        if s.events and s.events[-1].data == events[-1][1]:
            sid = s.id
    r = await client.get(f"/api/analyze/{sid}/events")
    assert r.text.count("event: ") == len(events)


async def test_simplify_level2_keeps_placeholders(client):
    events = await run_session(client, "arrears", answer="김해시")
    result = events[-1][1]
    r = await client.post("/api/simplify", json={"docId": result["docId"]})
    assert r.status_code == 200
    level2 = r.json()
    assert level2["level"] == 2
    assert set(level2) == {"level", "summaryTemplate", "consequences", "terms"}
    import re

    ph = lambda s: set(re.findall(r"\{(\w+)\}", s))  # noqa: E731
    assert ph(level2["summaryTemplate"]) == ph(result["explanation"]["summaryTemplate"])


async def test_simplify_expired(client):
    r = await client.post("/api/simplify", json={"docId": "nope"})
    assert r.status_code == 404
    assert r.json() == {"code": "server", "message": "시간이 지나서 다시 설명할 수 없어요. 문서를 다시 찍어 주세요"}


async def test_stored_result_has_no_contact_fields(client):
    from app.sessions.manager import get_manager

    events = await run_session(client, "smishing")
    stored = get_manager().get_result(events[-1][1]["docId"])
    assert "phone" not in stored.document["fields"] and "url" not in stored.document["fields"]


@pytest.mark.parametrize(
    "filename, content, ctype",
    [
        ("a.txt", b"hello", "text/plain"),
        ("a.jpg", b"not an image", "image/jpeg"),
        ("a.gif", b"GIF89a" + b"\x00" * 20, "image/gif"),
    ],
)
async def test_unsupported_upload(client, filename, content, ctype):
    r = await client.post("/api/analyze", files={"image": (filename, content, ctype)})
    assert r.status_code == 415
    assert r.json() == {"code": "unsupported_image", "message": "이 사진은 열 수 없어요. 카메라로 다시 찍어 주세요"}


async def test_too_large_upload(client):
    big = jpeg_bytes() + b"\x00" * (10 * 1024 * 1024)
    r = await client.post("/api/analyze", files={"image": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 415


async def test_png_and_webp_accepted(client):
    import io

    from PIL import Image

    for fmt, ctype in (("PNG", "image/png"), ("WEBP", "image/webp")):
        buf = io.BytesIO()
        Image.new("RGBA", (300, 200), (255, 255, 255, 0)).save(buf, fmt)
        r = await client.post("/api/analyze", files={"image": (f"a.{fmt.lower()}", buf.getvalue(), ctype)}, data={"scenario": "local_tax"})
        assert r.status_code == 200


async def test_unknown_session(client):
    r = await client.get("/api/analyze/nope/events")
    assert r.status_code == 404
    assert r.json() == {"code": "server", "message": "처음부터 다시 해 주세요"}
    r = await client.post("/api/analyze/nope/answer", json={"field": "region", "value": "김해시"})
    assert r.status_code == 404


async def test_health(client):
    r = await client.get("/api/health")
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize("scenario", ["arrears", "blurry", "smishing", "local_tax", "error"])
async def test_scripted_mode(client, set_mode, scenario):
    """AGENT_MODE=scripted: 프론트 목업과 같은 시나리오 키 재생."""
    set_mode("scripted")
    events = await run_session(client, scenario, answer="김해시")
    assert_contract(events)
    expected_end = {"blurry": "need_retake", "error": "error"}.get(scenario, "result")
    assert names(events)[-1] == expected_end
    if scenario == "arrears":
        assert "need_info" in names(events)
        r = await client.post("/api/simplify", json={"docId": events[-1][1]["docId"]})
        assert r.json()["level"] == 2


def test_client_key_ignores_spoofed_forwarded_for():
    """요청 수 제한: 클라이언트가 넣은 X-Forwarded-For 첫 값이 아니라 엣지가 정한 주소로 구분한다."""
    from starlette.requests import Request

    from app.api.routes_analyze import _client_key

    def req(headers: dict[str, str]) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "headers": raw, "client": ("172.18.0.5", 1234)})

    assert _client_key(req({"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4, 203.0.113.7"})) == "203.0.113.7"
    assert _client_key(req({"X-Forwarded-For": "1.2.3.4, 198.51.100.9"})) == "198.51.100.9"
    assert _client_key(req({})) == "172.18.0.5"
