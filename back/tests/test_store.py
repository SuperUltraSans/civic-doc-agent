"""SQLite 저장소 — DB 경로를 쓸 수 없을 때 임시 폴더로 넘어가는지."""

from __future__ import annotations

import os
import stat

import pytest

from app.config import get_settings
from app.store import db


@pytest.mark.skipif(os.geteuid() == 0, reason="root 는 권한 검사를 건너뛴다")
def test_init_db_falls_back_when_data_dir_not_writable(tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)  # 읽기 전용 (compose 마운트 + 다른 사용자 상황)
    fallback = tmp_path / "fallback" / "app.db"
    monkeypatch.setattr(db, "fallback_db_path", lambda: fallback)
    settings = get_settings()
    monkeypatch.setattr(settings, "db_path", locked / "sub" / "app.db")
    try:
        db.init_db()
        assert settings.db_path == fallback
        assert fallback.exists()
        assert db.all_welfare_rows()  # 사본도 새 위치에 들어간다
    finally:
        locked.chmod(stat.S_IRWXU)
