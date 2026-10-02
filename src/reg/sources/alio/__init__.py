from reg.sources.alio.handler import HANDLER

HANDLERS = [HANDLER]

from pathlib import Path  # noqa: E402

from reg.platform.db.migrate import MigrationLocation  # noqa: E402

MIGRATIONS = MigrationLocation("alio", Path(__file__).resolve().parent / "migrations", "regulation",
                               "alembic_version_alio")
