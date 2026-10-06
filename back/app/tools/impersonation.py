"""check_impersonation — 사칭 확인 (지시서 5.7절 (1)).

판정은 코드 규칙이 내린다. LLM은 사칭 수법 자료 중 "실제로 해당하는 것"을 고르는 데만 관여한다.
문서 내용이 LLM을 속이더라도 판정이 뒤집히지 않게 하기 위함이다.
어떤 경우에도 "안전하다"는 값이나 문구를 만들지 않는다.

공식 번호 찾는 순서: 시드 표(agencies.json) → 캐시(SQLite) → 실시간 검색(.go.kr·공식 도메인만) → 없음.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from app.config import get_settings
from app.llm.client import LLMError, get_llm, load_prompt
from app.llm.schemas import ScamSelectOut
from app.rag.retriever import ScamPattern, get_retriever
from app.schemas.tools import ImpersonationResult
from app.store.db import CachedAgency, get_cached_agency, save_cached_agency
from app.timeutil import today
from app.tools.web_search import search_official_phone

MOBILE_PREFIXES = ("010", "011", "016", "017", "018", "019")

FLAG_MESSAGES: dict[str, str] = {
    "mobile": "기관이라면서 휴대전화 번호로 연락하라고 해요",
    "phone_differs": "적힌 번호가 공식 번호와 달라요",
    "shortener": "짧게 줄인 인터넷 주소가 있어요",
    "not_official": "공식 홈페이지 주소가 아니에요",
    "lookalike": "공식 주소와 철자가 비슷한 주소예요",
    "insecure": "보호되지 않는 주소(http)예요",
}
# 코드 규칙 경고와 뜻이 겹치는 수법 자료 (같은 경고를 두 번 보여주지 않게)
_DUPLICATE_OF_RULE: dict[str, str] = {
    "kisa-001": "shortener",
    "kisa-016": "lookalike",
    "kisa-017": "insecure",
    "police-004": "mobile",
    "fss-010": "phone_differs",
}
# 코드 검사 결과를 수법 검색어로 바꾼 것
_SIGNAL_WORDS: dict[str, str] = {
    "mobile": "휴대전화 010 개인 번호",
    "phone_differs": "번호로 전화 문의 대표번호",
    "shortener": "단축 주소 링크 클릭 유도",
    "not_official": "인터넷 주소 링크 접속",
    "lookalike": "유사 주소 철자 비슷 가짜 홈페이지",
    "insecure": "http 보안 연결 아님",
    "has_url": "인터넷 주소 링크 접속",
}


# ── 데이터 ──
@dataclass(frozen=True)
class Agency:
    name: str
    short_name: str
    aliases: tuple[str, ...]
    phones: tuple[str, ...]
    domains: tuple[str, ...]
    source_url: str
    checked_at: str | None


@lru_cache
def load_agencies() -> tuple[Agency, ...]:
    raw: list[dict[str, Any]] = json.loads((get_settings().data_dir / "agencies.json").read_text(encoding="utf-8"))
    return tuple(
        Agency(
            name=r["name"],
            short_name=r.get("shortName") or r["name"],
            aliases=tuple(r.get("aliases") or ()),
            phones=tuple(r.get("officialPhones") or ()),
            domains=tuple(d.lower() for d in r.get("officialDomains") or ()),
            source_url=r.get("sourceUrl", ""),
            checked_at=r.get("checkedAt"),
        )
        for r in raw
    )


@lru_cache
def load_shorteners() -> frozenset[str]:
    path = get_settings().data_dir / "shortener_domains.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#"))


def _compact(text: str) -> str:
    return re.sub(r"\s", "", text or "")


def resolve_agency(issuer: str | None) -> Agency | None:
    """문서의 발신 기관 이름을 시드 표의 기관으로 맞춘다 (정확히 일치 → 포함 관계, 긴 이름 우선)."""
    target = _compact(issuer or "")
    if not target:
        return None
    best: tuple[int, Agency] | None = None
    for agency in load_agencies():
        for name in (agency.name, *agency.aliases):
            n = _compact(name)
            if not n:
                continue
            if n == target:
                return agency
            if len(n) >= 2 and (n in target or (len(target) >= 3 and target in n)):
                if best is None or len(n) > best[0]:
                    best = (len(n), agency)
    return best[1] if best else None


# 기관장 직위 → 기관 이름 ("서울특별시 종로구청장" → "서울특별시 종로구"). 실시간 검색·캐시 키에 쓴다.
_TITLE_SUFFIXES: tuple[tuple[str, str], ...] = (("구청장", "구"), ("시장", "시"), ("군수", "군"), ("도지사", "도"), ("청장", "청"))


def organization_name(issuer: str | None) -> str:
    name = re.sub(r"\s+", " ", (issuer or "").strip())
    for title, unit in _TITLE_SUFFIXES:
        if name.endswith(title) and len(name) > len(title):
            return name[: -len(title)] + unit
    return name


# ── 전화번호 ──
def normalize_phone(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("82") and len(digits) >= 10:  # +82 10-... → 010-...
        digits = "0" + digits[2:]
    return digits


def is_valid_phone(raw: str | None) -> bool:
    """문서에 적힌 번호 형식 검사: 숫자만 남겨 8~11자리 (대표번호 8자리 포함).

    지시서 규칙에 더해 1355·110·182 같은 1로 시작하는 3~4자리 특수번호도 허용한다
    (국민연금공단 등 공공기관 대표번호가 이 형식이다).
    """
    digits = normalize_phone(raw)
    return 8 <= len(digits) <= 11 or bool(re.fullmatch(r"1\d{2,3}", digits))


def is_mobile(digits: str) -> bool:
    return digits.startswith(MOBILE_PREFIXES)


def format_phone(raw: str) -> str:
    d = normalize_phone(raw)
    if len(d) <= 4:
        return d
    if len(d) == 8:  # 1577-1000
        return f"{d[:4]}-{d[4:]}"
    if d.startswith("02"):
        return f"02-{d[2:-4]}-{d[-4:]}"
    if len(d) in (10, 11):
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"
    return d


# ── 주소 ──
def domain_of(url: str | None) -> str:
    if not url:
        return ""
    raw = url.strip()
    try:
        host = urlsplit(raw if "://" in raw else f"http://{raw}").hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def is_official_domain(host: str, official_domains: list[str] | tuple[str, ...]) -> bool:
    return bool(host) and any(host == d or host.endswith(f".{d}") for d in official_domains)


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_lookalike(host: str, official_domains: list[str] | tuple[str, ...]) -> bool:
    """공식 도메인과 철자가 거의 같은 도메인 (편집 거리 2 이하), 또는 공식 이름을 끼워 넣은 도메인."""
    if not host or is_official_domain(host, official_domains):
        return False
    for d in official_domains:
        if edit_distance(host, d) <= 2:
            return True
        label = d.split(".")[0]
        if len(label) >= 4 and label in host:
            return True
        host_label = host.split(".")[0]
        if len(label) >= 4 and host_label != label and edit_distance(host_label, label) <= 1:
            return True
    return False


def check_url(url: str | None, official_domains: list[str] | tuple[str, ...]) -> list[str]:
    """주소 검사 (코드 규칙). 공식 도메인을 모르면 '공식 아님·유사 철자' 검사는 하지 않는다."""
    if not url:
        return []
    host = domain_of(url)
    issues: list[str] = []
    if not host:
        return ["not_official"]
    shorteners = load_shorteners()
    if host in shorteners or any(host.endswith(f".{s}") for s in shorteners):
        issues.append("shortener")
    if official_domains and not is_official_domain(host, official_domains) and not host.endswith(".go.kr"):
        issues.append("not_official")
        if is_lookalike(host, official_domains):
            issues.append("lookalike")
    if url.strip().lower().startswith("http://"):
        issues.append("insecure")
    return issues


# ── 판정 (코드 규칙, 지시서 5.7절 판정 규칙 표) ──
def decide_verdict(
    *,
    doc_phone: str | None,
    doc_url: str | None,
    official_phones: list[str] | tuple[str, ...],
    official_domains: list[str] | tuple[str, ...],
    url_issues: list[str],
    rag_flag_count: int,
) -> str:
    """match / mismatch / unknown. 오탐을 줄이기 위해 보수적으로 판정한다."""
    phone = normalize_phone(doc_phone)
    official_set = {normalize_phone(p) for p in official_phones}
    host = domain_of(doc_url)
    url_official = bool(doc_url) and (is_official_domain(host, official_domains) or host.endswith(".go.kr"))

    phone_match = bool(phone) and phone in official_set
    if not url_issues and (phone_match or (not phone and url_official)):
        return "match"

    phone_differs = bool(phone) and bool(official_set) and not phone_match
    url_differs = bool(doc_url) and bool(official_domains) and not url_official
    # 공식 도메인(.go.kr·공식 목록) 주소가 http:// 로 적힌 것만으로는 사칭 신호로 보지 않는다.
    # 종이 고지서는 공식 주소를 http 로 적는 일이 흔하고, 적힌 번호가 부서 번호라 대표번호와 다르면
    # 진짜 고지서가 '사칭 의심'으로 뒤집힌다 (오탐을 줄이는 보수적 판정, 지시서 5.7절). 경고 문구는 그대로 보여 준다.
    risky_url_issues = [i for i in url_issues if not (i == "insecure" and url_official)]
    risky = (bool(phone) and is_mobile(phone)) or bool(risky_url_issues) or rag_flag_count >= 1
    if (phone_differs or url_differs) and risky:
        return "mismatch"
    return "unknown"


# ── 공식 정보 찾기 (Memory: 검색 결과는 캐시에 쌓는다) ──
@dataclass
class OfficialInfo:
    name: str
    short_name: str
    phones: list[str]
    domains: list[str]
    source_desc: str | None
    kind: str  # seed | cache | search | domains_only


async def find_official_info(issuer: str | None) -> tuple[OfficialInfo | None, str]:
    agency = resolve_agency(issuer)
    if agency and agency.phones:
        checked = f", {agency.checked_at} 확인" if agency.checked_at else ""
        return (
            OfficialInfo(
                name=agency.name,
                short_name=agency.short_name,
                phones=[format_phone(p) for p in agency.phones],
                domains=list(agency.domains),
                source_desc=f"{agency.name} 공식 홈페이지({agency.domains[0] if agency.domains else agency.source_url}{checked})",
                kind="seed",
            ),
            f"seed table hit: {agency.name}",
        )
    name = agency.name if agency else organization_name(issuer)
    if not name:
        return None, "기관 이름 없음 → 공식 번호 없음"
    cached = get_cached_agency(name)
    if cached and cached.phones:
        return (
            OfficialInfo(
                name=name,
                short_name=agency.short_name if agency else name,
                phones=[format_phone(p) for p in cached.phones],
                domains=sorted(set(cached.domains) | set(agency.domains if agency else ())),
                source_desc=f"{name} 공식 페이지 검색 결과({domain_of(cached.source_url)}, {cached.checked_at} 확인)",
                kind="cache",
            ),
            f"cache hit: {name}",
        )
    found, search_note = await search_official_phone(name, list(agency.domains) if agency else [])
    if found:
        save_cached_agency(
            CachedAgency(name=name, phones=found.phones, domains=found.domains, source_url=found.source_url, checked_at=today().isoformat())
        )
        return (
            OfficialInfo(
                name=name,
                short_name=agency.short_name if agency else name,
                phones=[format_phone(p) for p in found.phones],
                domains=sorted(set(found.domains) | set(agency.domains if agency else ())),
                source_desc=f"{name} 공식 페이지 검색 결과({domain_of(found.source_url)}, {today().isoformat()} 확인)",
                kind="search",
            ),
            f"web search hit: {name} ({search_note}) → cache 저장",
        )
    if agency:
        return (
            OfficialInfo(name=agency.name, short_name=agency.short_name, phones=[], domains=list(agency.domains), source_desc=None, kind="domains_only"),
            f"seed table: {agency.name} (번호 미등록) / 검색 실패: {search_note}",
        )
    return None, f"공식 정보 없음: 시드·캐시 없음, 검색 실패({name}: {search_note})"


def who_label(issuer: str | None) -> str:
    """단계 문구용 기관 이름 ('공단', '김해시청' 등)."""
    agency = resolve_agency(issuer)
    if agency:
        return agency.short_name
    return (issuer or "").strip() or "기관"


# ── 수법 검사 (RAG) ──
@dataclass
class ScamCheck:
    flags: list[tuple[ScamPattern, str]] = field(default_factory=list)
    candidate_ids: list[str] = field(default_factory=list)
    note: str = ""


async def scam_pattern_check(document: dict[str, Any], excerpt: str | None, signal_codes: list[str]) -> ScamCheck:
    query_parts = [excerpt or "", document.get("docTypeLabel", ""), document.get("issuer", "")]
    query_parts += [_SIGNAL_WORDS[c] for c in signal_codes if c in _SIGNAL_WORDS]
    # 이미 코드 규칙으로 잡은 경고와 뜻이 같은 수법은 후보에서 빼고 상위 3개를 쓴다
    found = get_retriever().search(" ".join(query_parts), k=10)
    candidates = [c for c in found if _DUPLICATE_OF_RULE.get(c.id) not in signal_codes][:3]
    if not candidates:
        return ScamCheck(note="수법 후보 없음")
    payload = {
        "docType": document.get("docType"),
        "issuer": document.get("issuer"),
        "detectedSignals": [FLAG_MESSAGES.get(c, c) for c in signal_codes if c != "has_url"],
        "excerpt": (excerpt or "")[:600],
        "candidates": [{"id": c.id, "pattern": c.pattern, "signals": list(c.signals)} for c in candidates],
    }
    ids = [c.id for c in candidates]
    try:
        out = await get_llm().structured(
            role="fast",
            node="scam_select",
            system=load_prompt("scam_select"),
            user=json.dumps(payload, ensure_ascii=False),
            schema=ScamSelectOut,
        )
    except LLMError as exc:
        return ScamCheck(candidate_ids=ids, note=f"수법 선택 실패({type(exc).__name__}) → 수법 경고 없이 진행")
    by_id = {c.id: c for c in candidates}
    picked = [(by_id[s.id], s.evidence) for s in out.selected if s.id in by_id]
    dropped = [s.id for s in out.selected if s.id not in by_id]
    note = f"수법 후보 {','.join(ids)} → 근거 {','.join(p.id for p, _ in picked) or '없음'}"
    if dropped:
        note += f" (목록 밖 {len(dropped)}개 버림)"
    return ScamCheck(flags=picked, candidate_ids=ids, note=note)


# ── 도구 본체 ──
@dataclass
class ImpersonationOutcome:
    result: dict[str, Any]
    detail: str
    who: str
    official: OfficialInfo | None


# 문자가 아닌 고지서·안내문에서 수법 검사를 할 만한 구체적 위험 신호 (코드 규칙으로 잡힌 것)
_CONCRETE_SIGNALS = frozenset({"mobile", "shortener", "not_official", "lookalike"})


def needs_scam_check(document: dict[str, Any], codes: list[str], url_official: bool) -> bool:
    """수법 검사(RAG + LLM 선택)를 할지.

    사칭 의심 문자는 항상 한다. 종이 고지서·안내문은 휴대전화 번호, 비공식·단축·유사 주소처럼
    구체적 위험 신호가 있을 때만 한다. 공식 주소가 적혀 있다는 것만으로 "링크 접속 유도" 같은 수법이
    골라져 진짜 고지서에 경고가 붙거나 '사칭 의심'으로 뒤집히는 일을 막는다 (실제 키 시험에서 확인, 오탐 줄이기).
    """
    if document.get("docType") == "suspicious_message":
        return True
    concrete = set(codes) & _CONCRETE_SIGNALS
    if "insecure" in codes and not url_official:
        concrete.add("insecure")
    return bool(concrete)


async def check_impersonation(document: dict[str, Any], excerpt: str | None, lookup_name: str | None = None) -> ImpersonationOutcome:
    """lookup_name: 공식 정보를 찾을 기관 이름 (기본은 문서의 발신 기관). 결과 검토 단계가 다른 이름으로 다시 찾을 때 쓴다."""
    fields = document.get("fields") or {}
    doc_phone, doc_url = fields.get("phone"), fields.get("url")
    official, source_note = await find_official_info(lookup_name or document.get("issuer"))
    phones = official.phones if official else []
    domains = official.domains if official else []

    url_issues = check_url(doc_url, domains)
    phone = normalize_phone(doc_phone)
    codes: list[str] = []
    if phone and is_mobile(phone):
        codes.append("mobile")
    if phone and phones and phone not in {normalize_phone(p) for p in phones}:
        codes.append("phone_differs")
    codes += url_issues
    if doc_url:
        codes.append("has_url")

    # 공식 정보와 일치하면 수법 검사를 건너뛴다 (판정에 영향 없음, 시간 절약)
    pre = decide_verdict(doc_phone=doc_phone, doc_url=doc_url, official_phones=phones, official_domains=domains, url_issues=url_issues, rag_flag_count=0)
    host = domain_of(doc_url)
    url_official = bool(doc_url) and (is_official_domain(host, domains) or host.endswith(".go.kr"))
    if pre == "match":
        scam = ScamCheck(note="공식 정보와 일치 → 수법 검사 생략")
    elif not needs_scam_check(document, codes, url_official):
        scam = ScamCheck(note="문자가 아닌 문서 + 구체적 위험 신호 없음 → 수법 검사 생략")
    else:
        scam = await scam_pattern_check(document, excerpt, codes)
    rag_flags = [(p, ev) for p, ev in scam.flags if _DUPLICATE_OF_RULE.get(p.id) not in codes]
    rag_flag_count = len(scam.flags)

    status = decide_verdict(
        doc_phone=doc_phone, doc_url=doc_url, official_phones=phones, official_domains=domains, url_issues=url_issues, rag_flag_count=rag_flag_count
    )

    red_flags: list[str] = []
    for code in codes:
        msg = FLAG_MESSAGES.get(code)
        if msg and msg not in red_flags:
            red_flags.append(msg)
    for pattern, _ in rag_flags:
        if pattern.user_message not in red_flags:
            red_flags.append(pattern.user_message)

    checked = " / ".join(v for v in (format_phone(doc_phone) if phone else None, doc_url) if v)
    result = ImpersonationResult(
        status=status,  # type: ignore[arg-type]
        checked_value=checked or "",
        official_phone=phones[0] if phones else None,
        official_source=official.source_desc if official and phones else None,
        red_flags=red_flags,
    ).to_api()

    rule_ids = [f"rule:{c}" for c in codes if c in FLAG_MESSAGES]
    detail_parts = [
        source_note,
        f"공식 번호 {len(phones)}개 비교" if phones else "공식 번호 없음",
        f"주소 검사: {','.join(url_issues) or '이상 없음'}" if doc_url else None,
        scam.note,
        f"근거: {', '.join(rule_ids + [p.id for p, _ in scam.flags]) or '없음'}",
        f"판정 {status}",
    ]
    return ImpersonationOutcome(
        result=result,
        detail=" | ".join(p for p in detail_parts if p),
        who=official.short_name if official else who_label(document.get("issuer")),
        official=official,
    )
