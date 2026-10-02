from reg.sources.alio.handler import HANDLER

HANDLERS = [HANDLER]

from pathlib import Path

from reg.platform.db.migrate import MigrationLocation

MIGRATIONS = MigrationLocation("alio", Path(__file__).resolve().parent / "migrations", "regulation",
                               "alembic_version_alio")
