"""질의 로그 (spec 8.5, 11)."""
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("""
CREATE TABLE regulation.qa_log (
  id bigserial PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  question text NOT NULL,
  institution text,
  user_institution text,
  as_of date,
  status text NOT NULL,
  verdict text,
  release_id text,
  model text,
  retrieved jsonb NOT NULL DEFAULT '[]',
  cited jsonb NOT NULL DEFAULT '[]',
  verification jsonb NOT NULL DEFAULT '{}',
  answer jsonb,
  latency_ms int,
  feedback text
);""")


def downgrade() -> None:
    op.execute("DROP TABLE regulation.qa_log")
