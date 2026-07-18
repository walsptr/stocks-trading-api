"""Create BSJP backtesting tables."""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "20260716_0009"
down_revision: str | None = "20260716_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    bind = op.get_bind()
    status = postgresql.ENUM("running", "succeeded", "failed", name="backtest_run_status")
    status.create(bind, checkfirst=True)
    op.create_table("backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", postgresql.ENUM("running", "succeeded", "failed", name="backtest_run_status", create_type=False), nullable=False),
        sa.Column("backtest_version", sa.String(64), nullable=False),
        sa.Column("backtest_config_checksum", sa.String(64), nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("strategy_config_checksum", sa.String(64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_table("backtest_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False), sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=False), sa.Column("entry_price", sa.Numeric(20,6), nullable=False),
        sa.Column("exit_price", sa.Numeric(20,6), nullable=False), sa.Column("gross_return", sa.Numeric(24,12), nullable=False),
        sa.Column("net_return", sa.Numeric(24,12), nullable=False), sa.Column("buy_fee", sa.Numeric(24,6), nullable=False),
        sa.Column("sell_fee", sa.Numeric(24,6), nullable=False), sa.Column("gross_profit", sa.Numeric(24,6), nullable=False),
        sa.Column("net_profit", sa.Numeric(24,6), nullable=False), sa.Column("holding_sessions", sa.Integer(), nullable=False))
    op.create_index("ix_backtest_trades_run_symbol", "backtest_trades", ["run_id", "symbol", "signal_date"])
    op.create_table("backtest_symbol_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False), sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", name="uq_backtest_symbol_metric"))

def downgrade() -> None:
    op.drop_table("backtest_symbol_metrics")
    op.drop_index("ix_backtest_trades_run_symbol", table_name="backtest_trades")
    op.drop_table("backtest_trades"); op.drop_table("backtest_runs")
    postgresql.ENUM(name="backtest_run_status").drop(op.get_bind(), checkfirst=True)
