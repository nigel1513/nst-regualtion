from pathlib import Path

from reg.platform.db.migrate import MigrationLocation
from reg.sources.lawgo.handler import HANDLER

HANDLERS = [HANDLER]
MIGRATIONS = MigrationLocation("lawgo", Path(__file__).resolve().parent / "migrations", "law", "alembic_version")
