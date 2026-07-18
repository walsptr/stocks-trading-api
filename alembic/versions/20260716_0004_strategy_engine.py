"""Create configurable strategy engine tables."""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0004"
down_revision: str | None = "20260716_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

strategy_run_mode = postgresql.ENUM("rebuild", "update", name="strategy_run_mode", create_type=False)
strategy_run_status = postgresql.ENUM("running", "succeeded", "partial_failure", "failed", name="strategy_run_status", create_type=False)
strategy_symbol_status = postgresql.ENUM("success", "no_data", "failed", name="strategy_symbol_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    strategy_run_mode.create(bind, checkfirst=True)
    strategy_run_status.create(bind, checkfirst=True)
    strategy_symbol_status.create(bind, checkfirst=True)
    op.create_table(
        "daily_strategy_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("strategy_config_checksum", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean()),
        sa.Column("evaluation_details", postgresql.JSONB(), nullable=False),
        sa.Column("source_rule_formula_version", sa.String(64), nullable=False),
        sa.Column("source_rule_config_checksum", sa.String(64), nullable=False),
        sa.Column("source_rule_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("security_id", "provider", "interval", "trading_date", "strategy_name", "strategy_version", "strategy_config_checksum", name="uq_daily_strategy_result_identity"),
    )
    op.create_index("ix_daily_strategy_results_security_date", "daily_strategy_results", ["security_id", "trading_date"])
    op.create_table(
        "strategy_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", strategy_run_mode, nullable=False),
        sa.Column("status", strategy_run_status, nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("strategy_config_checksum", sa.String(64), nullable=False),
        sa.Column("source_rule_formula_version", sa.String(64), nullable=False),
        sa.Column("source_rule_config_checksum", sa.String(64), nullable=False),
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
        "strategy_symbol_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("strategy_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", strategy_symbol_status, nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", name="uq_strategy_run_symbol"),
    )


def downgrade() -> None:
    op.drop_table("strategy_symbol_results")
    op.drop_table("strategy_runs")
    op.drop_index("ix_daily_strategy_results_security_date", table_name="daily_strategy_results")
    op.drop_table("daily_strategy_results")
    bind = op.get_bind()
    strategy_symbol_status.drop(bind, checkfirst=True)
    strategy_run_status.drop(bind, checkfirst=True)
    strategy_run_mode.drop(bind, checkfirst=True)
