"""Tests for articlebot storage: migration, insert, file dump, mark_published."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def test_migrate_add_articles_executes_create_table_and_indexes():
    """The migration runs three statements: CREATE TABLE + 2 CREATE INDEX,
    all with IF NOT EXISTS so it's idempotent."""
    import database

    cur = MagicMock()
    database._migrate_add_articles(cur)

    sqls = [call.args[0] for call in cur.execute.call_args_list]
    assert len(sqls) == 3, f"expected 3 statements, got {len(sqls)}"
    assert "CREATE TABLE IF NOT EXISTS articles" in sqls[0]
    assert "run_id" in sqls[0] and "TEXT NOT NULL UNIQUE" in sqls[0]
    assert "alert_ids" in sqls[0] and "INTEGER[]" in sqls[0]
    assert "status" in sqls[0]
    assert "CREATE INDEX IF NOT EXISTS idx_articles_event_slug" in sqls[1]
    assert "CREATE INDEX IF NOT EXISTS idx_articles_status" in sqls[2]
