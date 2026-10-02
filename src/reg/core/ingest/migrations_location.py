"""core(regulation·ops 공통) 마이그레이션 위치."""
from pathlib import Path

from reg.platform.db.migrate import MigrationLocation

MIGRATIONS = MigrationLocation("core", Path(__file__).resolve().parents[1] / "migrations", "regulation",
                               "alembic_version")
