"""실시간 공식 번호 검색 — 실패 이유가 실행 기록에 남는지 (가짜 HTTP 응답, 실제 API 호출 없음)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import get_settings
from app.tools.web_search import extract_phones_near, name_variants, search_official_phone

NAME = "서울특별시 종로구청"
GOV_PAGE = f"<html><body><footer>{NAME} 삼봉로 43 대표전화 02-2148-1114 팩스 02-2148-5800</footer></body></html>"
# 구청 홈페이지에는 보통 시·도를 뗀 이름만 적혀 있다
SHORT_PAGE = "<html><body><footer>종로구청 (03153) 삼봉로 43 대표전화 02-2148-1114</footer></body></html>"


@pytest.fixture
def naver_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def search_api(links: list[str], status: int = 200, seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response | None:
        if request.url.host in ("naverapihub.apigw.ntruss.com", "openapi.naver.com"):
            if seen is not None:
                seen.append(request)
            return httpx.Response(status, json={"items": [{"link": u} for u in links]})
        return None

    return handler


async def test_hub_endpoint_and_headers_by_default(naver_keys):
    """검색 API는 NAVER API HUB 로 이관됐다: 주소·인증 헤더가 HUB 방식이어야 한다."""
    seen: list[httpx.Request] = []
    await search_official_phone(NAME, [], transport=transport(search_api([], seen=seen)))
    req = seen[0]
    assert str(req.url).startswith("https://naverapihub.apigw.ntruss.com/search/v1/webkr?")
    assert req.url.params["query"] == f"{NAME} 대표번호"
    assert req.headers["X-NCP-APIGW-API-KEY-ID"] == "id" and req.headers["X-NCP-APIGW-API-KEY"] == "secret"
    assert "X-Naver-Client-Id" not in req.headers


async def test_developers_endpoint_option(naver_keys, monkeypatch):
    monkeypatch.setenv("NAVER_SEARCH_API", "developers")
    get_settings.cache_clear()
    seen: list[httpx.Request] = []
    await search_official_phone(NAME, [], transport=transport(search_api([], seen=seen)))
    req = seen[0]
    assert req.url.host == "openapi.naver.com" and req.url.path == "/v1/search/webkr.json"
    assert req.headers["X-Naver-Client-Id"] == "id" and req.headers["X-Naver-Client-Secret"] == "secret"


def transport(*handlers, page: httpx.Response | None = None, slow: bool = False) -> httpx.AsyncBaseTransport:
    async def handle(request: httpx.Request) -> httpx.Response:
        for h in handlers:
            r = h(request)
            if r is not None:
                return r
        if slow:
            await asyncio.sleep(10)
        return page or httpx.Response(404)

    return httpx.MockTransport(handle)


async def test_no_keys(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "")
    get_settings.cache_clear()
    found, note = await search_official_phone(NAME, [])
    assert found is None and "검색 키 없음" in note
    get_settings.cache_clear()


async def test_search_api_error(naver_keys):
    found, note = await search_official_phone(NAME, [], transport=transport(search_api([], status=401)))
    assert found is None and "검색 API HTTP 401" in note


async def test_no_official_domain_results(naver_keys):
    t = transport(search_api(["https://blog.example/a", "https://namu.example/b"]))
    found, note = await search_official_phone(NAME, [], transport=t)
    assert found is None
    assert "공식 도메인(.go.kr·공식 목록) 결과 없음" in note and "검색 결과 2건 중 공식 도메인 0건" in note


async def test_page_without_agency_name(naver_keys):
    t = transport(search_api(["https://www.jongno.go.kr/x"]), page=httpx.Response(200, text="<html>다른 기관 1588-0000</html>"))
    found, note = await search_official_phone(NAME, [], transport=t)
    assert found is None and "jongno.go.kr" in note and "기관명 없음" in note


async def test_found_official_number(naver_keys):
    t = transport(search_api(["https://blog.example/a", "https://www.jongno.go.kr/x"]), page=httpx.Response(200, text=GOV_PAGE))
    found, note = await search_official_phone(NAME, [], transport=t)
    assert found is not None and found.phones[0] == "02-2148-1114"
    assert found.domains == ["jongno.go.kr"]
    assert "번호 1개" in note or "번호 2개" in note


async def test_overall_timeout_reports_stage(naver_keys, monkeypatch):
    monkeypatch.setenv("EXTERNAL_TIMEOUT_SECONDS", "0.3")
    get_settings.cache_clear()
    t = transport(search_api(["https://www.jongno.go.kr/x"]), slow=True)
    found, note = await search_official_phone(NAME, [], transport=t)
    assert found is None and "초과(jongno.go.kr 페이지 확인 중)" in note


@pytest.mark.parametrize(
    "name, variants",
    [
        ("서울특별시 종로구청", ["서울특별시 종로구청", "종로구청"]),
        ("경상남도 김해시청", ["경상남도 김해시청", "김해시청"]),
        ("부산광역시 중구청", ["부산광역시 중구청", "중구청"]),
        ("서울특별시 종로구", ["서울특별시 종로구"]),  # 지역 이름만 남으면 다른 기관 페이지에도 흔히 나온다
        ("국민건강보험공단", ["국민건강보험공단"]),
        ("종로구청", ["종로구청"]),
    ],
)
def test_name_variants(name, variants):
    assert name_variants(name) == variants


async def test_short_office_name_on_page_is_accepted(naver_keys):
    """검색은 전체 이름으로 하고, 페이지에는 시·도를 뗀 관청 이름만 있어도 채택한다."""
    seen: list[httpx.Request] = []
    t = transport(search_api(["https://www.jongno.go.kr/x"], seen=seen), page=httpx.Response(200, text=SHORT_PAGE))
    found, note = await search_official_phone(NAME, [], transport=t)
    assert seen[0].url.params["query"] == "서울특별시 종로구청 대표번호"
    assert found is not None and found.phones[0] == "02-2148-1114"
    assert "'종로구청' 확인" in note


async def test_bare_region_name_is_not_enough(naver_keys):
    """'종로구'만 있는 페이지(경찰서 등)의 번호는 채택하지 않는다."""
    page = httpx.Response(200, text="<html>서울종로경찰서 종로구 율곡로 대표전화 02-0000-1182</html>")
    t = transport(search_api(["https://www.smpa.go.kr/x"]), page=page)
    found, note = await search_official_phone(NAME, [], transport=t)
    assert found is None and "기관명 없음" in note


# 같은 공식 도메인의 보건소 페이지: 상단 메뉴에 "종로구청"이 있지만 대표전화는 보건소 번호이고 멀리 떨어져 있다
# (2026-10-06 실제 시험에서 jongno.go.kr/healthMain.do 의 보건소 번호를 구청 번호로 잘못 채택했던 구조)
HEALTH_PAGE = "<html>최상단 메뉴 종로구청 종로구의회 보건소 " + "공지 " * 300 + "전화번호 안내 대표전화 02-2148-3520 제증명 02-2148-3524</html>"
MAIN_PAGE = "<html>" + "소식 " * 300 + "종로구청 위치 및 전화번호, 사이트 정보 [03142]서울특별시 종로구 종로1길 50 대표전화: 02-2148-1114(120다산콜센터로 연결)</html>"


def test_name_far_from_representative_number_is_ignored():
    assert extract_phones_near(HEALTH_PAGE, "종로구청") == []
    assert extract_phones_near(MAIN_PAGE, "종로구청")[0] == "02-2148-1114"


def test_number_right_after_name_without_representative_label():
    assert extract_phones_near("<p>종로구청 TEL 02-2148-1114</p>", "종로구청") == ["02-2148-1114"]
    assert extract_phones_near("<p>종로구청 안내</p>" + "글 " * 100 + "문의 02-2148-3520", "종로구청") == []


async def test_health_center_page_skipped_then_main_page_used(naver_keys):
    pages = {"/healthMain.do": HEALTH_PAGE, "/": MAIN_PAGE}

    def site(request: httpx.Request) -> httpx.Response | None:
        if request.url.host == "www.jongno.go.kr":
            return httpx.Response(200, text=pages[request.url.path])
        return None

    t = transport(search_api(["https://www.jongno.go.kr/healthMain.do", "https://www.jongno.go.kr/"]), site)
    found, note = await search_official_phone(NAME, [], transport=t)
    assert found is not None and found.phones[0] == "02-2148-1114" and found.source_url == "https://www.jongno.go.kr/"
    assert "기관명 근처 대표번호 없음" in note


def test_number_cut_at_window_end_is_not_split():
    """창 끝에 걸린 번호(02-2148-1111)를 잘라 "111" 같은 특수번호 조각으로 채택하지 않는다."""
    text = "종로구청 정보 대표전화: 02-2148-1114(120다산콜센터로 연결) 02-2148-1111,1112,1113(야간)"
    phones = extract_phones_near(text, "종로구청")
    assert phones[0] == "02-2148-1114" and "111" not in phones
