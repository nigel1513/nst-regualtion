"""개정 영향·담당자·알림 (spec 5.3, 9)."""
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("""
CREATE TABLE regulation.change_impact (
  id bigserial PRIMARY KEY,
  cause_work_id text NOT NULL,
  cause_version_id text NOT NULL,
  cause_from_version_id text,
  cause_path text NOT NULL,
  cause_change text NOT NULL CHECK (cause_change IN ('ADDED', 'MODIFIED', 'DELETED', 'RENUMBERED')),
  affected_work_id text NOT NULL,
  affected_version_id text,
  affected_path text NOT NULL,
  rel_type text NOT NULL,
  evidence text,
  impact_kind text NOT NULL,
  severity text NOT NULL CHECK (severity IN ('HIGH', 'MEDIUM', 'LOW')),
  hops int NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'ACKED', 'ACTION_REQUIRED', 'NO_ACTION', 'RESOLVED')),
  resolution_note text,
  resolved_by_version_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cause_version_id, cause_path, affected_work_id, affected_path)
);
CREATE INDEX ON regulation.change_impact (status, severity);
CREATE TABLE regulation.owner_assignment (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL,
  email text NOT NULL,
  name text,
  org_unit text,
  role text NOT NULL DEFAULT 'OWNER' CHECK (role IN ('OWNER', 'DEPUTY')),
  UNIQUE (work_id, email)
);
CREATE TABLE regulation.notification (
  id bigserial PRIMARY KEY,
  impact_id bigint NOT NULL REFERENCES regulation.change_impact(id) ON DELETE CASCADE,
  recipient text NOT NULL,
  channel text NOT NULL DEFAULT 'email',
  severity text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz,
  sent_at timestamptz,
  UNIQUE (impact_id, recipient)
);
CREATE TABLE regulation.email_delivery (
  id bigserial PRIMARY KEY,
  recipient text NOT NULL,
  subject text NOT NULL,
  body text NOT NULL,
  notification_ids bigint[] NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
  attempts int NOT NULL DEFAULT 0,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);""")


def downgrade() -> None:
    op.execute("DROP TABLE regulation.email_delivery; DROP TABLE regulation.notification;"
               " DROP TABLE regulation.owner_assignment; DROP TABLE regulation.change_impact;")
