"""Create technical ranking agent tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0006"
down_revision: str | None = "20260716_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ranking_run_mode = postgresql.ENUM("rebuild", "update", name="ranking_run_mode", create_type=False)
ranking_run_status = postgresql.ENUM(
    "running", "succeeded", "partial_failure", "failed",
    name="ranking_run_status", create_type=False,
)
ranking_date_status = postgresql.ENUM(
    "success", "no_data", "failed", name="ranking_date_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    ranking_run_mode.create(bind, checkfirst=True)
    ranking_run_status.create(bind, checkfirst=True)
    ranking_date_status.create(bind, checkfirst=True)
    op.create_table(
        "daily_rankings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("ranking_version", sa.String(64), nullable=False),
        sa.Column("ranking_config_checksum", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(32), nullable=False),
        sa.Column("source_scoring_version", sa.String(64), nullable=False),
        sa.Column("source_scoring_config_checksum", sa.String(64), nullable=False),
        sa.Column("source_scored_at", sa.DateTime(timezone=True)),
        sa.Column("ranked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "security_id", "provider", "interval", "trading_date",
            "ranking_version", "ranking_config_checksum", name="uq_daily_ranking_identity",
        ),
    )
    op.create_index(
        "ix_daily_rankings_snapshot", "daily_rankings",
        ["ranking_version", "ranking_config_checksum", "trading_date", "rank"],
    )
    op.create_table(
        "ranking_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", ranking_run_mode, nullable=False),
        sa.Column("status", ranking_run_status, nullable=False),
        sa.Column("ranking_version", sa.String(64), nullable=False),
        sa.Column("ranking_config_checksum", sa.String(64), nullable=False),
        sa.Column("source_scoring_version", sa.String(64), nullable=False),
        sa.Column("source_scoring_config_checksum", sa.String(64), nullable=False),
        sa.Column("requested_start_date", sa.Date()),
        sa.Column("requested_end_date", sa.Date()),
        sa.Column("requested_dates", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("no_data_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "ranking_date_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ranking_runs.id"), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("status", ranking_date_status, nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "trading_date", name="uq_ranking_run_date"),
    )


def downgrade() -> None:
    op.drop_table("ranking_date_results")
    op.drop_table("ranking_runs")
    op.drop_index("ix_daily_rankings_snapshot", table_name="daily_rankings")
    op.drop_table("daily_rankings")
    bind = op.get_bind()
    ranking_date_status.drop(bind, checkfirst=True)
    ranking_run_status.drop(bind, checkfirst=True)
    ranking_run_mode.drop(bind, checkfirst=True)
