import os
import sys
import time
from types import SimpleNamespace

import psycopg

from reg.ops import tasks
from reg.platform.settings import get_settings


def _seed_logs(conn):
    conn.execute("INSERT INTO ops.request_log (source, url, at) VALUES"
                 " ('alio', 'old', now() - interval '91 days'), ('alio', 'new', now() - interval '89 days')")
    conn.execute("INSERT INTO ops.qa_log (question, status, created_at) VALUES"
                 " ('old', 'ok', now() - interval '366 days'), ('new', 'ok', now() - interval '364 days')")
    conn.commit()


def test_prune_log_files(tmp_path):
    now = time.time()
    old, new = tmp_path / "dag_id=a" / "old.log", tmp_path / "dag_id=a" / "new.log"
    old.parent.mkdir()
    old.write_text("x")
    new.write_text("y")
    os.utime(old, (now - 31 * 86400, now - 31 * 86400))
    assert tasks.prune_log_files(tmp_path, days=30, now=now) == 1
    assert not old.exists() and new.exists() and old.parent.is_dir()
    assert tasks.prune_log_files(tmp_path / "missing") == 0


def test_maintenance_prunes_old_rows_logs_and_indexes(conn, app_dsn, monkeypatch, tmp_path):
    _seed_logs(conn)
    log = tmp_path / "old.log"
    log.write_text("x")
    os.utime(log, (time.time() - 40 * 86400,) * 2)
    monkeypatch.setenv("REG_AIRFLOW_LOG_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setitem(sys.modules, "reg.index.tasks", SimpleNamespace(prune=lambda: {"deleted": ["r1"]}))
    st = tasks.maintenance()
    assert st == {"request_log_deleted": 1, "qa_log_deleted": 1, "airflow_logs_deleted": 1,
                  "index_prune": {"deleted": ["r1"]}}
    with psycopg.connect(app_dsn) as c:
        assert [r[0] for r in c.execute("SELECT url FROM ops.request_log")] == ["new"]
        assert [r[0] for r in c.execute("SELECT question FROM ops.qa_log")] == ["new"]


def test_prune_indexes_skips_when_m6_4_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "reg.index.tasks", SimpleNamespace(build=dict))
    assert tasks._prune_indexes() == {"skipped": "reg.index.tasks.prune 없음 (M6-4 병합 전)"}
    monkeypatch.setitem(sys.modules, "reg.index.tasks", None)
    assert tasks._prune_indexes() == {"skipped": "reg.index.tasks 없음"}


def test_maintenance_without_log_dir(conn, app_dsn, monkeypatch):
    monkeypatch.delenv("REG_AIRFLOW_LOG_DIR", raising=False)
    get_settings.cache_clear()
    monkeypatch.setitem(sys.modules, "reg.index.tasks", SimpleNamespace(prune=lambda: {"deleted": []}))
    assert tasks.maintenance()["airflow_logs_deleted"] == 0
