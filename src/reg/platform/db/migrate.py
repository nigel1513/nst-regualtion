"""모듈별 Alembic 이력(위치)을 순서대로 head까지 올린다 (overview §2.4)."""
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config


@dataclass(frozen=True)
class MigrationLocation:
    name: str
    path: Path
    schema: str
    version_table: str


def alembic_config(migrator_dsn: str, loc: MigrationLocation) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(loc.path))
    cfg.set_main_option("sqlalchemy.url", migrator_dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    cfg.set_main_option("version_table_schema", loc.schema)
    cfg.set_main_option("version_table", loc.version_table)
    return cfg


def upgrade(migrator_dsn: str, locations: list[MigrationLocation], revision: str = "head") -> None:
    for loc in locations:
        command.upgrade(alembic_config(migrator_dsn, loc), revision)
