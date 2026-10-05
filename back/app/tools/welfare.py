"""search_welfare — 복지 연계 (지시서 5.7절 (3)).

절차
1. 상황 태그: 문서 종류와 필드에서 코드로 만든다.
2. 후보 검색: 공공데이터포털 한국사회보장정보원 복지서비스 API(중앙부처·지자체). 실패하거나 5초를 넘기면
   미리 받아 둔 사본(welfare_snapshot.csv → SQLite)으로 검색하고 fallbackUsed=true. 후보 최대 20개.
3. 재정렬: LLM이 후보 중 최대 3개를 고르고 이유를 쓴다. 후보 밖 제도는 버린다.
4. 복지멤버십 안내를 항상 마지막에 붙인다.
5. 요약·이유는 "해당될 수 있어요" 수준. 자격을 단정하지 않는다.

※ API 경로·요청 변수·응답 필드는 공공데이터포털 명세로 다시 확인할 것 (README 참고).
"""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

from app.config import get_settings
from app.llm.client import LLMError, get_llm, load_prompt
from app.llm.schemas import WelfareRerankOut
from app.store.db import all_welfare_rows
from app.textutil import is_assertive

NATIONAL_LIST_URL = "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfarelistV001"
LOCAL_LIST_URL = "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfarelist"
LIFE_ELDERLY = "006"  # 생애주기: 노년

MEMBERSHIP_ITEM: dict[str, Any] = {
    "name": "복지멤버십(맞춤형 급여 안내)",
    "summary": "한 번 가입해 두면 받을 수 있을지 모르는 복지 제도를 찾아서 알려 줘요. 주민센터나 복지로에서 신청할 수 있어요.",
    "reason": "앞으로 해당될 수 있는 제도를 놓치지 않도록 함께 안내해요.",
    "url": "https://www.bokjiro.go.kr",
    "region": "",
    "fixed": True,
}
MAX_CANDIDATES = 20
MAX_PICKS = 3


@lru_cache
def region_sido_map() -> dict[str, str | None]:
    raw = json.loads((get_settings().data_dir / "regions.json").read_text(encoding="utf-8"))
    return {o["value"]: o.get("sido") for o in raw["options"]}


def effective_region(profile: dict[str, Any]) -> str | None:
    region = (profile or {}).get("region")
    if not region or region == "기타":
        return None
    return str(region)


def situation_tags(document: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    """문서 종류·필드에서 코드로 상황 태그를 만든다."""
    doc_type = document.get("docType")
    fields = document.get("fields") or {}
    tags: list[str] = []
    if (fields.get("arrears") or 0) > 0:
        tags += ["체납", "분할납부", "긴급지원", "생계"]
    if doc_type == "health_insurance_bill":
        tags += ["건강보험", "보험료"]
    elif doc_type == "local_tax_bill":
        tags += ["지방세"]
    elif doc_type == "fine_notice":
        tags += ["과태료"]
    elif doc_type == "basic_pension_notice":
        tags += ["노인", "기초연금", "저소득"]
    if (fields.get("amount") or 0) >= 300_000:
        tags += ["저소득", "생계"]
    if (profile or {}).get("ageGroup"):
        tags += ["노인"]
    return list(dict.fromkeys(tags)) or ["노인", "저소득"]


def _score(text: str, tags: list[str]) -> int:
    return sum(1 for t in tags if t in text)


# ── 후보 검색: API ──
def _text(item: ET.Element, tag: str) -> str:
    return (item.findtext(tag) or "").strip()


def _parse_serv_list(xml_text: str, kind: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    rows: list[dict[str, Any]] = []
    for item in root.iter("servList"):
        name = _text(item, "servNm")
        if not name:
            continue
        region = (_text(item, "sggNm") or _text(item, "ctpvNm")) if kind == "local" else ""
        rows.append(
            {
                "id": _text(item, "servId") or name,
                "name": name,
                "summary": _text(item, "servDgst"),
                "url": _text(item, "servDtlLink") or "https://www.bokjiro.go.kr",
                "region": region,
                "tags": "",
            }
        )
    return rows


async def _api_candidates(tags: list[str], region: str | None, elderly: bool) -> list[dict[str, Any]]:
    s = get_settings()
    key = s.secret(s.data_go_kr_service_key)
    if not key:
        raise RuntimeError("DATA_GO_KR_SERVICE_KEY 없음")
    keywords = tags[:2]
    async with httpx.AsyncClient(timeout=s.external_timeout_seconds) as client:
        calls = []
        for word in keywords:
            params = {"serviceKey": key, "callTp": "L", "pageNo": 1, "numOfRows": 10, "srchKeyCode": "003", "searchWrd": word}
            if elderly:
                params["lifeArray"] = LIFE_ELDERLY
            calls.append(("national", client.get(NATIONAL_LIST_URL, params=params)))
        sido = region_sido_map().get(region or "")
        if region and sido:
            for word in keywords[:1]:
                params = {"serviceKey": key, "pageNo": 1, "numOfRows": 10, "ctpvNm": sido, "sggNm": region, "srchKeyCode": "003", "searchWrd": word}
                calls.append(("local", client.get(LOCAL_LIST_URL, params=params)))
        responses = await asyncio.gather(*(c for _, c in calls), return_exceptions=True)
    rows: list[dict[str, Any]] = []
    ok = 0
    for (kind, _), resp in zip(calls, responses, strict=True):
        if isinstance(resp, BaseException) or resp.status_code != 200:
            continue
        try:
            rows += _parse_serv_list(resp.text, kind)
            ok += 1
        except ET.ParseError:
            continue
    if ok == 0:
        raise RuntimeError("복지 API 응답 없음")
    return rows


# ── 후보 검색: 사본 ──
def _snapshot_candidates(tags: list[str], region: str | None) -> list[dict[str, Any]]:
    sido = region_sido_map().get(region or "")
    rows = []
    for r in all_welfare_rows():
        item_region = r.get("sgg") or r.get("ctpv") or ""
        if item_region and item_region not in (region, sido):
            continue
        rows.append(
            {
                "id": r["serv_id"],
                "name": r["name"],
                "summary": r["summary"],
                "url": r["url"],
                "region": item_region,
                "tags": r.get("tags") or "",
            }
        )
    return rows


def _rank(rows: list[dict[str, Any]], tags: list[str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique = []
    for r in rows:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        r["score"] = _score(f"{r['name']} {r['summary']} {r.get('tags', '')}", tags)
        unique.append(r)
    unique.sort(key=lambda r: r["score"], reverse=True)
    return [r for r in unique if r["score"] > 0][:MAX_CANDIDATES]


# ── 재정렬 (LLM) ──
async def _rerank(candidates: list[dict[str, Any]], tags: list[str], document: dict[str, Any], situation: str, region: str | None) -> tuple[list[dict[str, Any]], str]:
    by_id = {c["id"]: c for c in candidates}
    payload = {
        "situation": situation,
        "docTypeLabel": document.get("docTypeLabel"),
        "tags": tags,
        "hasRegion": region is not None,
        "region": region,
        "candidates": [{"id": c["id"], "name": c["name"], "summary": c["summary"][:160], "region": c["region"] or "전국"} for c in candidates],
    }
    try:
        out = await get_llm().structured(
            role="fast",
            node="welfare_rerank",
            system=load_prompt("welfare_rerank"),
            user=json.dumps(payload, ensure_ascii=False),
            schema=WelfareRerankOut,
        )
    except LLMError as exc:
        picks = [{**c, "reason": _default_reason(c, tags)} for c in candidates[:MAX_PICKS]]
        return picks, f"재정렬 실패({type(exc).__name__}) → 점수 상위 {len(picks)}건"
    picks: list[dict[str, Any]] = []
    dropped = 0
    for p in out.items:
        cand = by_id.get(p.id)
        if cand is None:
            dropped += 1
            continue
        if any(x["id"] == cand["id"] for x in picks):
            continue
        reason = p.reason.strip()
        if not reason or is_assertive(reason) or any(ch.isdigit() for ch in reason):
            reason = _default_reason(cand, tags)
        picks.append({**cand, "reason": reason})
        if len(picks) >= MAX_PICKS:
            break
    note = f"재정렬 {len(picks)}건 선택"
    if dropped:
        note += f", 후보 밖 {dropped}건 버림"
    return picks, note


def _default_reason(candidate: dict[str, Any], tags: list[str]) -> str:
    text = f"{candidate['name']} {candidate['summary']} {candidate.get('tags', '')}"
    hit = next((t for t in tags if t in text), None)
    return f"문서에 '{hit}' 관련 내용이 있어 해당될 수 있어요." if hit else "문서 상황과 관련이 있어 해당될 수 있어요."


@dataclass
class WelfareOutcome:
    result: dict[str, Any]  # items 안에 내부용 region 키가 남아 있다 (compose 에서 제거)
    detail: str


async def search_welfare(
    document: dict[str, Any],
    profile: dict[str, Any],
    situation: str,
    *,
    ignore_region: bool = False,
) -> WelfareOutcome:
    region = None if ignore_region else effective_region(profile)
    tags = situation_tags(document, profile)
    elderly = bool((profile or {}).get("ageGroup")) or document.get("docType") == "basic_pension_notice"
    fallback = False
    try:
        raw = await asyncio.wait_for(_api_candidates(tags, region, elderly), timeout=get_settings().external_timeout_seconds)
        source = "공공데이터 API"
    except Exception as exc:  # 키 없음·시간 초과·응답 오류 → 사본
        raw = _snapshot_candidates(tags, region)
        fallback = True
        source = f"사본 데이터(API 실패: {type(exc).__name__ if not isinstance(exc, RuntimeError) else exc})"
    candidates = _rank(raw, tags)
    picks, rerank_note = await _rerank(candidates, tags, document, situation, region) if candidates else ([], "후보 없음")
    items = [{k: p[k] for k in ("name", "summary", "reason", "url", "region")} for p in picks]
    items.append(dict(MEMBERSHIP_ITEM))
    result = {"items": items, "usedProfile": region is not None, "fallbackUsed": fallback}
    detail = f"태그 {','.join(tags)} | 지역 {'반영: ' + region if region else '미반영'} | {source} 후보 {len(candidates)}건 | {rerank_note}"
    return WelfareOutcome(result=result, detail=detail)


def searched_count(result: dict[str, Any]) -> int:
    """고정 항목(복지멤버십)을 뺀 검색 결과 수."""
    return sum(1 for i in result.get("items", []) if not i.get("fixed"))
