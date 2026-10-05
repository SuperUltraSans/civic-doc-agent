"""SQLite 접근 — 기관 정보 캐시(agency_cache)와 복지 데이터 사본(welfare).

개인정보는 넣지 않는다. 세션·이미지·추출 결과는 이 DB에 쓰지 않는다 (지시서 8장).
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.config import get_settings
from app.logging_setup import log_event
from app.timeutil import now_iso

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS agency_cache (
    name        TEXT PRIMARY KEY,
    phones      TEXT NOT NULL,
    domains     TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS welfare (
    serv_id  TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    summary  TEXT NOT NULL,
    target   TEXT,
    ctpv     TEXT,
    sgg      TEXT,
    tags     TEXT,
    url      TEXT NOT NULL,
    source   TEXT,
    kind     TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = path or get_settings().sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
    load_welfare_snapshot()


# ── 기관 정보 캐시 (Memory: 확인할 때마다 쌓인다) ──
@dataclass
class CachedAgency:
    name: str
    phones: list[str]
    domains: list[str]
    source_url: str
    checked_at: str


def get_cached_agency(name: str) -> CachedAgency | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM agency_cache WHERE name = ?", (name,)).fetchone()
    if row is None:
        return None
    return CachedAgency(
        name=row["name"],
        phones=json.loads(row["phones"]),
        domains=json.loads(row["domains"]),
        source_url=row["source_url"],
        checked_at=row["checked_at"],
    )


def save_cached_agency(agency: CachedAgency) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO agency_cache (name, phones, domains, source_url, checked_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET phones=excluded.phones, domains=excluded.domains,
                 source_url=excluded.source_url, checked_at=excluded.checked_at, updated_at=excluded.updated_at""",
            (
                agency.name,
                json.dumps(agency.phones, ensure_ascii=False),
                json.dumps(agency.domains, ensure_ascii=False),
                agency.source_url,
                agency.checked_at,
                now_iso(),
            ),
        )


# ── 복지 데이터 사본 (대체 경로) ──
def _snapshot_path() -> Path:
    return get_settings().data_dir / "welfare_snapshot.csv"


def load_welfare_snapshot(force: bool = False) -> int:
    """welfare_snapshot.csv 가 바뀌었으면 SQLite에 다시 넣는다."""
    path = _snapshot_path()
    if not path.exists():
        log_event("welfare snapshot missing", level=30, node="store")
        return 0
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='welfare_digest'").fetchone()
        if row and row["value"] == digest and not force:
            return conn.execute("SELECT COUNT(*) FROM welfare").fetchone()[0]
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        conn.execute("DELETE FROM welfare")
        conn.executemany(
            """INSERT OR REPLACE INTO welfare (serv_id, name, summary, target, ctpv, sgg, tags, url, source, kind)
               VALUES (:serv_id, :name, :summary, :target, :ctpv, :sgg, :tags, :url, :source, :kind)""",
            [{k: (r.get(k) or "").strip() for k in ("serv_id", "name", "summary", "target", "ctpv", "sgg", "tags", "url", "source", "kind")} for r in rows],
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('welfare_digest', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (digest,),
        )
    log_event("welfare snapshot loaded", node="store", count=len(rows))
    return len(rows)


def all_welfare_rows() -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM welfare")]
