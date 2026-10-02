"""버전별 원문 위치: 같은 조항 판본이 여러 버전에서 공유돼도 쪽 번호는 버전마다 다르다."""
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("ALTER TABLE regulation.version_provision ADD COLUMN anchor jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE regulation.version_provision DROP COLUMN anchor")
