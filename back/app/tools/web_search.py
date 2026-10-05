"""실시간 검색으로 기관 공식 번호 찾기 (지시서 5.7절 (1)-3).

- 네이버 검색 API로 "기관명 대표번호"를 검색한다.
- 결과 URL이 `.go.kr` 이거나 시드 표에 등록된 공식 도메인인 페이지만 쓴다.
- 그 페이지를 가져와, 기관명이 같은 페이지에 있을 때만 전화번호를 채택한다.
- 전체 5초 제한. 실패하면 None (호출한 쪽이 "공식 번호 없음"으로 진행).
"""

from __future__ import annotations

import asyncio
import html
import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.config import get_settings

NAVER_WEB_SEARCH = "https://openapi.naver.com/v1/search/webkr.json"
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


async def _search(agency_name: str, official_domains: list[str]) -> SearchFound | None:
    s = get_settings()
    client_id, secret = s.secret(s.naver_client_id), s.secret(s.naver_client_secret)
    if not client_id or not secret:
        return None
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": secret}
    async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
        resp = await client.get(NAVER_WEB_SEARCH, params={"query": f"{agency_name} 대표번호", "display": 10}, headers=headers)
        resp.raise_for_status()
        links = [item.get("link", "") for item in resp.json().get("items", [])]
        links = [u for u in links if is_allowed_host(host_of(u), official_domains)][:3]
        for url in links:
            try:
                page = await client.get(url, headers={"User-Agent": "ilgeodeurim/1.0"})
            except httpx.HTTPError:
                continue
            if page.status_code != 200:
                continue
            text = html.unescape(_TAG.sub(" ", page.text[:MAX_PAGE_BYTES]))
            phones = extract_phones_near(re.sub(r"\s+", " ", text), agency_name)
            if phones:
                host = host_of(url)
                return SearchFound(phones=phones, domains=[host], source_url=url)
    return None


async def search_official_phone(agency_name: str, official_domains: list[str]) -> SearchFound | None:
    try:
        return await asyncio.wait_for(_search(agency_name, official_domains), timeout=get_settings().external_timeout_seconds)
    except (TimeoutError, httpx.HTTPError, ValueError):
        return None
