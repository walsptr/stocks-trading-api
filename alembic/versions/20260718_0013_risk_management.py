"""Add deterministic ATR risk recommendations."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0013"
down_revision: str | None = "20260718_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

risk_run_mode = postgresql.ENUM("rebuild", "update", name="risk_run_mode", create_type=False)
risk_run_status = postgresql.ENUM("running", "succeeded", "partial_failure", "failed", name="risk_run_status", create_type=False)
risk_symbol_status = postgresql.ENUM("success", "no_data", "failed", name="risk_symbol_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    risk_run_mode.create(bind, checkfirst=True)
    risk_run_status.create(bind, checkfirst=True)
    risk_symbol_status.create(bind, checkfirst=True)
    op.create_table(
        "daily_risk_recommendations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("risk_version", sa.String(64), nullable=False),
        sa.Column("risk_config_checksum", sa.String(64), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("atr_14", sa.Numeric(24, 10), nullable=False),
        sa.Column("stop_loss", sa.Numeric(20, 6), nullable=False),
        sa.Column("take_profit", sa.Numeric(20, 6), nullable=False),
        sa.Column("risk_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("reward_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("reward_risk_ratio", sa.Numeric(24, 10), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source_indicator_version", sa.String(64), nullable=False),
        sa.Column("source_ranking_version", sa.String(64), nullable=False),
        sa.Column("source_ranking_config_checksum", sa.String(64), nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("security_id", "provider", "interval", "trading_date", "risk_version", "risk_config_checksum", name="uq_daily_risk_recommendation_identity"),
    )
    op.create_index("ix_daily_risk_recommendations_snapshot", "daily_risk_recommendations", ["risk_version", "risk_config_checksum", "trading_date", "rank"])
    op.create_table(
        "risk_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", risk_run_mode, nullable=False),
        sa.Column("status", risk_run_status, nullable=False),
        sa.Column("risk_version", sa.String(64), nullable=False),
        sa.Column("risk_config_checksum", sa.String(64), nullable=False),
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
        "risk_symbol_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("risk_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("status", risk_symbol_status, nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", "trading_date", name="uq_risk_run_symbol_date"),
    )


def downgrade() -> None:
    op.drop_table("risk_symbol_results")
    op.drop_table("risk_runs")
    op.drop_index("ix_daily_risk_recommendations_snapshot", table_name="daily_risk_recommendations")
    op.drop_table("daily_risk_recommendations")
    bind = op.get_bind()
    risk_symbol_status.drop(bind, checkfirst=True)
    risk_run_status.drop(bind, checkfirst=True)
    risk_run_mode.drop(bind, checkfirst=True)
