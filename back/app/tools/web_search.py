"""실시간 검색으로 기관 공식 번호 찾기 (지시서 5.7절 (1)-3).

- 네이버 웹문서 검색으로 "기관명 대표번호"를 검색한다. 검색 API는 2026년 NAVER Developers 에서
  NAVER API HUB 로 옮겨졌다(개발자센터 신규 발급 종료). 기본은 HUB, 예전 개발자센터 키는 NAVER_SEARCH_API=developers.
- 결과 URL이 `.go.kr` 이거나 시드 표에 등록된 공식 도메인인 페이지만 쓴다.
- 그 페이지를 가져와, 기관명이 같은 페이지에 있을 때만 전화번호를 채택한다.
- 전체 5초 제한. 실패하면 None + 실패 이유 (호출한 쪽이 "공식 번호 없음"으로 진행하고 이유를 실행 기록에 남긴다).
"""

from __future__ import annotations

import asyncio
import html
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.logging_setup import log_event

# NAVER API HUB (기본): https://api.ncloud-docs.com/docs/naver-api-hub-search-webkr
NAVER_HUB_WEB_SEARCH = "https://naverapihub.apigw.ntruss.com/search/v1/webkr"
# 예전 NAVER Developers 개발자센터 (이미 발급받은 키가 있을 때만)
NAVER_DEV_WEB_SEARCH = "https://openapi.naver.com/v1/search/webkr.json"
_PHONE = re.compile(r"(?<!\d)(1[5-9]\d{2}-\d{4}|0\d{1,2}-\d{3,4}-\d{4}|1\d{2})(?!\d)")
_TAG = re.compile(r"<[^>]+>")
MAX_PAGE_BYTES = 1_000_000


@dataclass
class SearchFound:
    phones: list[str]
    domains: list[str]
    source_url: str


def host_of(url: str) -> str:
    try:
        host = urlsplit(url if "://" in url else f"https://{url}").hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def is_allowed_host(host: str, official_domains: list[str]) -> bool:
    if host.endswith(".go.kr"):
        return True
    return any(host == d or host.endswith(f".{d}") for d in official_domains)


def extract_phones_near(text: str, agency_name: str) -> list[str]:
    """기관명이 페이지에 있을 때만, '대표' 근처 번호를 우선해 고른다. 휴대전화 번호는 버린다."""
    if agency_name not in text:
        return []
    near: list[str] = []
    for m in re.finditer(r"대표\s*(?:전화|번호)?", text):
        window = text[m.end() : m.end() + 40]
        near.extend(p for p in _PHONE.findall(window) if not p.startswith("01"))
    if near:
        return list(dict.fromkeys(near))[:3]
    counts = Counter(p for p in _PHONE.findall(text) if not p.startswith("01") and len(p) > 3)
    return [p for p, _ in counts.most_common(2)]


def naver_endpoint(client_id: str, secret: str) -> tuple[str, dict[str, str]]:
    """검색 창구별 주소·인증 헤더. 요청 변수와 응답 형식은 두 창구가 같다."""
    if get_settings().naver_search_api == "developers":
        return NAVER_DEV_WEB_SEARCH, {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": secret}
    return NAVER_HUB_WEB_SEARCH, {"X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": secret}


@dataclass
class SearchTrace:
    """검색이 어느 단계에서 멈췄는지 (실행 로그·서버 로그용). 기관 이름·도메인만 담고 개인정보는 없다."""

    stage: str = "검색 API 호출"
    results: int | None = None  # 네이버 검색 결과 수
    allowed: list[str] = field(default_factory=list)  # 그중 .go.kr·공식 도메인 결과 (호스트)
    pages: list[str] = field(default_factory=list)  # 페이지별 결과
    error: str | None = None

    def summary(self, elapsed_ms: int) -> str:
        parts: list[str] = []
        if self.error:
            parts.append(self.error)
        if self.results is not None:
            parts.append(f"검색 결과 {self.results}건 중 공식 도메인 {len(self.allowed)}건" + (f"({', '.join(self.allowed)})" if self.allowed else ""))
        if self.pages:
            parts.append("페이지: " + "; ".join(self.pages))
        parts.append(f"{elapsed_ms}ms")
        return ", ".join(parts)


async def _search(agency_name: str, official_domains: list[str], trace: SearchTrace, transport: httpx.AsyncBaseTransport | None = None) -> SearchFound | None:
    s = get_settings()
    client_id, secret = s.secret(s.naver_client_id), s.secret(s.naver_client_secret)
    if not client_id or not secret:
        trace.error = "검색 키 없음"
        return None
    url, headers = naver_endpoint(client_id, secret)
    async with httpx.AsyncClient(timeout=3.0, follow_redirects=True, transport=transport) as client:
        resp = await client.get(url, params={"query": f"{agency_name} 대표번호", "display": 10}, headers=headers)
        if resp.status_code != 200:
            trace.error = f"검색 API HTTP {resp.status_code}"
            return None
        links = [item.get("link", "") for item in resp.json().get("items", [])]
        trace.results = len(links)
        links = [u for u in links if is_allowed_host(host_of(u), official_domains)][:3]
        trace.allowed = [host_of(u) for u in links]
        if not links:
            trace.error = "공식 도메인(.go.kr·공식 목록) 결과 없음"
            return None
        for url in links:
            host = host_of(url)
            trace.stage = f"{host} 페이지 확인"
            try:
                page = await client.get(url, headers={"User-Agent": "ilgeodeurim/1.0"})
            except httpx.TimeoutException:
                trace.pages.append(f"{host} 시간 초과")
                continue
            except httpx.HTTPError as exc:
                trace.pages.append(f"{host} {type(exc).__name__}")
                continue
            if page.status_code != 200:
                trace.pages.append(f"{host} HTTP {page.status_code}")
                continue
            text = re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", page.text[:MAX_PAGE_BYTES])))
            info = f"{host} HTTP 200 ({page.encoding or '인코딩 모름'}, {len(text)}자)"
            if agency_name not in text:
                trace.pages.append(f"{info} 기관명 없음")
                continue
            phones = extract_phones_near(text, agency_name)
            if not phones:
                trace.pages.append(f"{info} 번호 없음")
                continue
            trace.pages.append(f"{info} 번호 {len(phones)}개")
            return SearchFound(phones=phones, domains=[host_of(str(page.url)) or host], source_url=url)
    return None


async def search_official_phone(
    agency_name: str, official_domains: list[str], *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[SearchFound | None, str]:
    """(찾은 공식 번호 또는 None, 검색 경과 설명). 실패 이유를 로그와 실행 기록에 남긴다."""
    trace = SearchTrace()
    timeout = get_settings().external_timeout_seconds
    started = time.perf_counter()
    found: SearchFound | None = None
    try:
        found = await asyncio.wait_for(_search(agency_name, official_domains, trace, transport), timeout=timeout)
    except TimeoutError:
        trace.error = f"전체 {timeout:g}초 초과({trace.stage} 중)"
    except (httpx.HTTPError, ValueError) as exc:
        trace.error = f"{type(exc).__name__}({trace.stage} 중)"
    elapsed = round((time.perf_counter() - started) * 1000)
    note = trace.summary(elapsed)
    log_event("official phone search", node="check_impersonation", status="hit" if found else "miss", agency=agency_name, durationMs=elapsed, detail=note)
    return found, note
