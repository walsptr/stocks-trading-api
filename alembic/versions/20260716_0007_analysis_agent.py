"""Create deterministic analysis agent tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0007"
down_revision: str | None = "20260716_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

analysis_run_mode = postgresql.ENUM("rebuild", "update", name="analysis_run_mode", create_type=False)
analysis_run_status = postgresql.ENUM(
    "running", "succeeded", "partial_failure", "failed",
    name="analysis_run_status", create_type=False,
)
analysis_symbol_status = postgresql.ENUM(
    "success", "no_data", "failed", name="analysis_symbol_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    analysis_run_mode.create(bind, checkfirst=True)
    analysis_run_status.create(bind, checkfirst=True)
    analysis_symbol_status.create(bind, checkfirst=True)
    op.create_table(
        "daily_analyses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        sa.Column("analysis_config_checksum", sa.String(64), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("bullish_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("caution_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("source_availability", postgresql.JSONB(), nullable=False),
        sa.Column("strategy_status", sa.String(16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("source_versions", postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "security_id", "provider", "interval", "trading_date",
            "analysis_version", "analysis_config_checksum", name="uq_daily_analysis_identity",
        ),
    )
    op.create_index(
        "ix_daily_analyses_snapshot", "daily_analyses",
        ["analysis_version", "analysis_config_checksum", "trading_date", "rank"],
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", analysis_run_mode, nullable=False),
        sa.Column("status", analysis_run_status, nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        sa.Column("analysis_config_checksum", sa.String(64), nullable=False),
        sa.Column("requested_start_date", sa.Date()),
        sa.Column("requested_end_date", sa.Date()),
        sa.Column("requested_symbols", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("no_data_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "analysis_symbol_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("status", analysis_symbol_status, nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", "trading_date", name="uq_analysis_run_symbol_date"),
    )


def downgrade() -> None:
    op.drop_table("analysis_symbol_results")
    op.drop_table("analysis_runs")
    op.drop_index("ix_daily_analyses_snapshot", table_name="daily_analyses")
    op.drop_table("daily_analyses")
    bind = op.get_bind()
    analysis_symbol_status.drop(bind, checkfirst=True)
    analysis_run_status.drop(bind, checkfirst=True)
    analysis_run_mode.drop(bind, checkfirst=True)
