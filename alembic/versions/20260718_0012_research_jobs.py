"""Create persistent research jobs."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0012"
down_revision: str | None = "20260717_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("job_type IN ('backtest', 'optimization')", name="ck_research_job_type"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')", name="ck_research_job_status"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_research_job_progress"),
    )
    op.create_index("ix_research_jobs_started_at", "research_jobs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_research_jobs_started_at", table_name="research_jobs")
    op.drop_table("research_jobs")
