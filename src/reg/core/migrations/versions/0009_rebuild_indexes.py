"""재적재·검수 경로의 인덱스 (docs/tech/03-rdb.md §8): work_id로 지우는 두 테이블, 대상만으로 찾는 검수 작업."""
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute("""
CREATE INDEX IF NOT EXISTS provision_change_work ON regulation.provision_change (work_id);
CREATE INDEX IF NOT EXISTS reference_work ON regulation.reference (work_id);
CREATE INDEX IF NOT EXISTS review_task_target ON regulation.review_task (target);
""")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS regulation.provision_change_work, regulation.reference_work,"
               " regulation.review_task_target")
