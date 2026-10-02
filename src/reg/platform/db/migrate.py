from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parents[2] / "core" / "migrations"


def alembic_config(migrator_dsn: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", migrator_dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    return cfg


def upgrade(migrator_dsn: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(migrator_dsn), revision)
