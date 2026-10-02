import os
import subprocess
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]


def test_metadata_db_script_is_idempotent(pg):
    env = {**os.environ, "PG_CONTAINER": pg.get_wrapped_container().name, "PG_SUPERUSER": pg.username,
           "REG_AIRFLOW_DB_PASSWORD": "af-pass-1"}
    for pw in ("af-pass-1", "af-pass-2"):        # 두 번째는 비밀번호 변경까지 반영되는지
        env["REG_AIRFLOW_DB_PASSWORD"] = pw
        r = subprocess.run(["bash", "scripts/airflow-metadata-db.sh"], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
    with psycopg.connect(f"postgresql://reg_airflow:af-pass-2@{host}:{port}/reg_airflow", autocommit=True) as c:
        c.execute("CREATE TABLE IF NOT EXISTS probe (id int)")   # Airflow가 public 스키마에 테이블을 만들 수 있다
        assert c.execute("SELECT current_database()").fetchone()[0] == "reg_airflow"
