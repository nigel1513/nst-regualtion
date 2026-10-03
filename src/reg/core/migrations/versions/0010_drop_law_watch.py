"""law_watch 폐기 (배치 스펙 §5.4): 쓰는 코드가 없다. 법령 감시는 law 스키마 미러가 맡는다."""
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regulation.law_watch")


def downgrade() -> None:
    pass  # 되살리지 않는다 (쓰는 코드 없음)
