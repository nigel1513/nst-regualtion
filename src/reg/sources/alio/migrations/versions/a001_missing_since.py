"""ALIO 목록에서 사라진 날 (폐지 감지, spec §3.3). alio 모듈 이력의 첫 리비전."""
from alembic import op

revision = "a001"
down_revision = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulation.alio_rule ADD COLUMN missing_since date")


def downgrade() -> None:
    op.execute("ALTER TABLE regulation.alio_rule DROP COLUMN missing_since")
