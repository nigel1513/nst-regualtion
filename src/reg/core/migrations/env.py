from alembic import context
from sqlalchemy import create_engine

url = context.config.get_main_option("sqlalchemy.url")
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, version_table_schema="regulation")
    with context.begin_transaction():
        context.run_migrations()
