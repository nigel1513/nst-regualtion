from alembic import context
from sqlalchemy import create_engine

cfg = context.config
engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
with engine.connect() as connection:
    context.configure(connection=connection, version_table_schema=cfg.get_main_option("version_table_schema"),
                      version_table=cfg.get_main_option("version_table"))
    with context.begin_transaction():
        context.run_migrations()
