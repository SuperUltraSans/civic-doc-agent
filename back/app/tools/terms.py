"""lookup_terms — 행정 용어 사전 검색 (지시서 5.7절 (4)).

찾는 순서: 정확히 일치 → 공백·조사 제거 후 일치.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.config import get_settings

# 용어 뒤에 붙는 흔한 조사 (긴 것부터)
_JOSA = ("으로는", "에서는", "이라는", "이란", "라는", "으로", "에서", "에게", "까지", "부터", "에는", "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "란")


@dataclass(frozen=True)
class TermEntry:
    term: str
    plain: str
    aliases: tuple[str, ...]
    doc_types: tuple[str, ...]
    source: str
    source_url: str


def normalize_term(text: str) -> str:
    t = re.sub(r"[\s·\-_()\[\]\"'“”‘’.,?!]", "", text.strip())
    for josa in _JOSA:
        if len(t) > len(josa) + 1 and t.endswith(josa):
            return t[: -len(josa)]
    return t


@lru_cache
def _load() -> tuple[TermEntry, ...]:
    path = get_settings().data_dir / "terms.json"
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        TermEntry(
            term=r["term"],
            plain=r["plain"],
            aliases=tuple(r.get("aliases") or ()),
            doc_types=tuple(r.get("docTypes") or ()),
            source=r.get("source", ""),
            source_url=r.get("sourceUrl", ""),
        )
        for r in raw
    )


@lru_cache
def _index() -> tuple[dict[str, TermEntry], dict[str, TermEntry]]:
    exact: dict[str, TermEntry] = {}
    normalized: dict[str, TermEntry] = {}
    for entry in _load():
        for name in (entry.term, *entry.aliases):
            exact.setdefault(name, entry)
            normalized.setdefault(normalize_term(name), entry)
    return exact, normalized


def lookup_term(term: str) -> TermEntry | None:
    exact, normalized = _index()
    if term in exact:
        return exact[term]
    return normalized.get(normalize_term(term))


def candidate_terms(doc_type: str, fields: dict[str, Any], excerpt: str | None, limit: int = 6) -> list[TermEntry]:
    """문서와 관련 있는 사전 항목 후보: 문서 발췌에 실제로 나온 용어 → 필드·문서 종류 관련 용어 순."""
    picked: list[TermEntry] = []

    def add(entry: TermEntry | None) -> None:
        if entry and entry not in picked:
            picked.append(entry)

    if excerpt:
        compact = re.sub(r"\s", "", excerpt)
        hits = [e for e in _load() if any(re.sub(r"\s", "", n) in compact for n in (e.term, *e.aliases) if n)]
        # 이 문서 종류 전용 용어 → 다른 종류 용어 → 어디에나 나오는 일반 용어(고지서 등) 순
        hits.sort(key=lambda e: 0 if doc_type in e.doc_types else (1 if e.doc_types else 2))
        for entry in hits:
            add(entry)
    if fields.get("arrears"):
        add(lookup_term("체납액"))
    if fields.get("amount") and doc_type in ("health_insurance_bill", "local_tax_bill", "fine_notice"):
        add(lookup_term("납기 내 금액"))
    if fields.get("dueDate"):
        add(lookup_term("납부기한"))
    if fields.get("url") and doc_type == "suspicious_message":
        add(lookup_term("단축 주소"))
    for entry in _load():
        if doc_type in entry.doc_types:
            add(entry)
    return picked[:limit]
