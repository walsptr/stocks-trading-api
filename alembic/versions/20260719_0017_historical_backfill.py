"""Create resumable historical backfill jobs."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260719_0017"
down_revision: str | None = "20260718_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_backfill_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_years", sa.Integer(), nullable=False),
        sa.Column("target_start_date", sa.Date(), nullable=False),
        sa.Column("target_end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_symbols", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_symbols", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_symbols", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial_symbols", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_symbols", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_data_symbols", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_symbol", sa.String(32)),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("target_years >= 1 AND target_years <= 5", name="ck_historical_backfill_target_years"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_historical_backfill_progress"),
    )
    op.create_index("ix_historical_backfill_jobs_started_at", "historical_backfill_jobs", ["started_at"])
    op.create_table(
        "historical_backfill_symbols",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("historical_backfill_jobs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("requested_start_date", sa.Date(), nullable=False),
        sa.Column("requested_end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_id", "symbol", name="uq_historical_backfill_job_symbol"),
    )
    op.create_index("ix_historical_backfill_symbols_status", "historical_backfill_symbols", ["job_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_historical_backfill_symbols_status", table_name="historical_backfill_symbols")
    op.drop_table("historical_backfill_symbols")
    op.drop_index("ix_historical_backfill_jobs_started_at", table_name="historical_backfill_jobs")
    op.drop_table("historical_backfill_jobs")
