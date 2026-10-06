"""실시간 검색으로 기관 공식 번호 찾기 (지시서 5.7절 (1)-3).

- 네이버 웹문서 검색으로 "기관명 대표번호"를 검색한다. 검색 API는 2026년 NAVER Developers 에서
  NAVER API HUB 로 옮겨졌다(개발자센터 신규 발급 종료). 기본은 HUB, 예전 개발자센터 키는 NAVER_SEARCH_API=developers.
- 결과 URL이 `.go.kr` 이거나 시드 표에 등록된 공식 도메인인 페이지만 쓴다.
- 그 페이지를 가져와, 기관명이 같은 페이지에 있을 때만 전화번호를 채택한다. 기관명은 적힌 그대로 또는
  시·도를 뗀 관청 이름("서울특별시 종로구청" → "종로구청")으로 확인한다 (홈페이지에는 보통 짧은 이름만 적혀 있다).
- 전체 5초 제한. 실패하면 None + 실패 이유 (호출한 쪽이 "공식 번호 없음"으로 진행하고 이유를 실행 기록에 남긴다).
"""

from __future__ import annotations

import asyncio
import html
import re
import time
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


_PROVINCE = re.compile(r"^\S+(?:특별시|광역시|특별자치시|특별자치도|도)\s+")


def name_variants(agency_name: str) -> list[str]:
    """페이지에서 찾을 기관 이름: 적힌 그대로, 그리고 시·도를 뗀 관청 이름.

    짧은 이름은 '청'으로 끝날 때만 쓴다 — "종로구"처럼 지역 이름만 남으면 다른 기관 페이지(경찰서 등)에도
    흔히 나와 엉뚱한 번호를 채택할 수 있다.
    """
    name = re.sub(r"\s+", " ", agency_name.strip())
    variants = [name] if name else []
    short = _PROVINCE.sub("", name)
    if short != name and short.endswith("청") and len(short) >= 3:
        variants.append(short)
    return variants


def matched_name(text: str, agency_name: str) -> str | None:
    """페이지에 있는 기관 이름 (없으면 None)."""
    return next((v for v in name_variants(agency_name) if v in text), None)


NAME_WINDOW = 150  # 기관명과 '대표전화' 사이 최대 글자 수
AFTER_NAME = 60  # 대표번호 표시가 없을 때 기관명 바로 뒤에서 번호를 찾는 범위


def extract_phones_near(text: str, agency_name: str) -> list[str]:
    """기관명 가까이에 적힌 대표번호만 고른다. 휴대전화 번호는 버린다.

    같은 공식 도메인 안에도 보건소·의회·사업소 페이지가 있고, 그 페이지 상단 메뉴에도 "○○구청"이 적혀 있다.
    기관명이 페이지 어딘가에 있다는 것만으로 대표번호를 채택하면 보건소 번호를 구청 번호로 잘못 고른다
    (2026-10-06 실제 시험: jongno.go.kr/healthMain.do 의 대표전화는 기관명에서 1,142자 떨어져 있었고,
    구청 메인 페이지는 53자). 그래서 기관명이 '대표전화' 앞뒤 NAME_WINDOW 글자 안에 있을 때만 채택한다.
    """
    names = [m.span() for m in re.finditer(re.escape(agency_name), text)]
    if not names:
        return []
    near: list[str] = []
    for m in re.finditer(r"대표\s*(?:전화|번호)?", text):
        close = any(0 <= m.start() - end <= NAME_WINDOW or 0 <= start - m.end() <= NAME_WINDOW for start, end in names)
        if close:
            near.extend(p for p in _phones_starting_within(text, m.end(), 40) if not p.startswith("01"))
    if not near:
        # '대표' 표시가 없으면 기관명 바로 뒤에 적힌 번호만 ("종로구청 TEL 02-…")
        for _, end in names:
            near.extend(p for p in _phones_starting_within(text, end, AFTER_NAME) if not p.startswith("01") and len(p) > 3)
    return list(dict.fromkeys(near))[:3]


def _phones_starting_within(text: str, pos: int, span: int) -> list[str]:
    """pos 뒤 span 글자 안에서 시작하는 번호. 범위 끝에서 번호를 잘라 "111" 같은 조각을 만들지 않게 전체 글에서 찾는다."""
    out: list[str] = []
    for m in _PHONE.finditer(text, pos):
        if m.start() > pos + span:
            break
        out.append(m.group(1))
    return out


def official_phones(text: str, agency_name: str) -> tuple[list[str], str | None]:
    """(번호, 번호 근처에서 확인한 기관 이름). 적힌 그대로의 이름부터 시·도를 뗀 이름 순으로 본다."""
    for name in name_variants(agency_name):
        phones = extract_phones_near(text, name)
        if phones:
            return phones, name
    return [], None


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
            if matched_name(text, agency_name) is None:
                trace.pages.append(f"{info} 기관명 없음")
                continue
            phones, found_name = official_phones(text, agency_name)
            if not phones:
                trace.pages.append(f"{info} 기관명 근처 대표번호 없음")
                continue
            trace.pages.append(f"{info} '{found_name}' 확인, 번호 {len(phones)}개")
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
