"""실시간 공식 번호 검색 — 실패 이유가 실행 기록에 남는지 (가짜 HTTP 응답, 실제 API 호출 없음)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import get_settings
from app.tools.web_search import search_official_phone

NAME = "서울특별시 종로구"
GOV_PAGE = f"<html><body><footer>{NAME} 삼봉로 43 대표전화 02-2148-1114 팩스 02-2148-5800</footer></body></html>"


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
