"""사칭 수법 RAG (지시서 5.8절).

기본: BM25(rank_bm25) + 한국어 형태소 분석(kiwipiepy). 자료가 작고 외부 호출이 없어 빠르고 안정적이다.
kiwipiepy를 쓸 수 없는 환경에서는 글자 2-gram 토크나이저로 대체한다.
`Retriever` 인터페이스를 두어 임베딩 검색으로 교체·병합할 수 있게 한다.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.config import get_settings
from app.logging_setup import log_event


@dataclass(frozen=True)
class ScamPattern:
    id: str
    pattern: str
    signals: tuple[str, ...]
    user_message: str
    source: str
    source_url: str

    @property
    def text(self) -> str:
        return " ".join((self.pattern, *self.signals, self.user_message))


class Retriever(Protocol):
    def search(self, query: str, k: int = 3) -> list[ScamPattern]: ...


def load_patterns() -> list[ScamPattern]:
    path = get_settings().data_dir / "scam_patterns.jsonl"
    out: list[ScamPattern] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out.append(
            ScamPattern(
                id=r["id"],
                pattern=r["pattern"],
                signals=tuple(r.get("signals") or ()),
                user_message=r["userMessage"],
                source=r.get("source", ""),
                source_url=r.get("sourceUrl", ""),
            )
        )
    return out


class _Tokenizer:
    _KEEP = ("NN", "VV", "VA", "XR", "SL", "SN", "SH", "MAG")

    def __init__(self) -> None:
        self._kiwi = None
        self._lock = threading.Lock()
        try:
            from kiwipiepy import Kiwi

            self._kiwi = Kiwi()
        except Exception:  # 설치 안 됨·모델 로딩 실패 → 2-gram 대체
            log_event("kiwipiepy unavailable → bigram tokenizer", level=30, node="rag")

    @property
    def kind(self) -> str:
        return "kiwi" if self._kiwi else "bigram"

    def __call__(self, text: str) -> list[str]:
        text = text.lower()
        if self._kiwi is not None:
            with self._lock:
                tokens = self._kiwi.tokenize(text)
            return [t.form for t in tokens if t.tag.startswith(self._KEEP)]
        words = re.findall(r"[가-힣]+|[a-z0-9]+", text)
        out: list[str] = []
        for w in words:
            if re.match(r"[가-힣]", w) and len(w) > 1:
                out.extend(w[i : i + 2] for i in range(len(w) - 1))
            else:
                out.append(w)
        return out


class BM25Retriever:
    def __init__(self, patterns: list[ScamPattern] | None = None) -> None:
        from rank_bm25 import BM25Okapi

        self.patterns = patterns if patterns is not None else load_patterns()
        self.tokenize = _Tokenizer()
        corpus = [self.tokenize(p.text) or ["_"] for p in self.patterns]
        self._bm25 = BM25Okapi(corpus)

    def search(self, query: str, k: int = 3) -> list[ScamPattern]:
        tokens = self.tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(self.patterns)), key=lambda i: scores[i], reverse=True)
        return [self.patterns[i] for i in ranked[:k] if scores[i] > 0]


@lru_cache
def get_retriever() -> Retriever:
    retriever = BM25Retriever()
    log_event("scam retriever ready", node="rag", patterns=len(retriever.patterns), tokenizer=retriever.tokenize.kind)
    return retriever


@lru_cache
def pattern_by_id() -> dict[str, ScamPattern]:
    return {p.id: p for p in load_patterns()}
