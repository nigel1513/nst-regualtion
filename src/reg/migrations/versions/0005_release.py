"""게시 버전(release): 검색 색인과 답변 근거를 같은 스냅샷으로 묶는다 (spec 7)."""
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""
CREATE TABLE regulation.release (
  id serial PRIMARY KEY,
  state text NOT NULL CHECK (state IN ('BUILDING', 'PUBLISHED', 'RETIRED', 'FAILED')),
  os_index text NOT NULL,
  embedding_model text NOT NULL,
  stats jsonb NOT NULL DEFAULT '{}',
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE TABLE regulation.release_item (
  release_id int NOT NULL REFERENCES regulation.release(id) ON DELETE CASCADE,
  work_version_id text NOT NULL,
  PRIMARY KEY (release_id, work_version_id)
);""")


def downgrade() -> None:
    op.execute("DROP TABLE regulation.release_item; DROP TABLE regulation.release;")
