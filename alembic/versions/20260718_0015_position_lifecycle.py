"""Create virtual Swing position lifecycle tables."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0015"
down_revision: str | None = "20260718_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

position_status = postgresql.ENUM("pending_entry", "open", "partial", "closed", name="position_status", create_type=False)
position_run_mode = postgresql.ENUM("rebuild", "update", name="position_run_mode", create_type=False)
position_run_status = postgresql.ENUM("running", "succeeded", "failed", name="position_run_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    position_status.create(bind, checkfirst=True)
    position_run_mode.create(bind, checkfirst=True)
    position_run_status.create(bind, checkfirst=True)
    op.create_table(
        "virtual_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("lifecycle_version", sa.String(64), nullable=False),
        sa.Column("lifecycle_config_checksum", sa.String(64), nullable=False),
        sa.Column("status", position_status, nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("entry_date", sa.Date()), sa.Column("exit_date", sa.Date()),
        sa.Column("signal_atr", sa.Numeric(24, 10)),
        sa.Column("entry_price", sa.Numeric(20, 6)),
        sa.Column("initial_stop", sa.Numeric(20, 6)),
        sa.Column("active_stop", sa.Numeric(20, 6)),
        sa.Column("take_profit_1", sa.Numeric(20, 6)),
        sa.Column("take_profit_2", sa.Numeric(20, 6)),
        sa.Column("highest_close", sa.Numeric(20, 6)),
        sa.Column("remaining_fraction", sa.Numeric(12, 8), nullable=False),
        sa.Column("suggested_position_size_pct", sa.Numeric(12, 6), nullable=False),
        sa.Column("holding_sessions", sa.Integer(), nullable=False),
        sa.Column("queued_action", sa.String(32)), sa.Column("queued_action_date", sa.Date()),
        sa.Column("tp1_filled", sa.Boolean(), nullable=False),
        sa.Column("realized_gross_return", sa.Numeric(24, 10), nullable=False),
        sa.Column("realized_net_return", sa.Numeric(24, 10), nullable=False),
        sa.Column("unrealized_return", sa.Numeric(24, 10)),
        sa.Column("exit_reason", sa.String(32)),
        sa.Column("average_exit_price", sa.Numeric(20, 6)),
        sa.Column("last_processed_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_virtual_positions_status_symbol", "virtual_positions", ["status", "symbol"])
    op.create_index("ix_virtual_positions_symbol_signal", "virtual_positions", ["symbol", "signal_date"])
    op.create_table(
        "position_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("virtual_positions.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False), sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False), sa.Column("price", sa.Numeric(20, 6)),
        sa.Column("fraction", sa.Numeric(12, 8)), sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_position_events_position_date", "position_events", ["position_id", "trading_date"])
    op.create_table(
        "position_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", position_run_mode, nullable=False), sa.Column("status", position_run_status, nullable=False),
        sa.Column("lifecycle_version", sa.String(64), nullable=False),
        sa.Column("lifecycle_config_checksum", sa.String(64), nullable=False),
        sa.Column("positions_count", sa.Integer(), nullable=False), sa.Column("events_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("position_runs")
    op.drop_index("ix_position_events_position_date", table_name="position_events")
    op.drop_table("position_events")
    op.drop_index("ix_virtual_positions_symbol_signal", table_name="virtual_positions")
    op.drop_index("ix_virtual_positions_status_symbol", table_name="virtual_positions")
    op.drop_table("virtual_positions")
    bind = op.get_bind()
    position_run_status.drop(bind, checkfirst=True)
    position_run_mode.drop(bind, checkfirst=True)
    position_status.drop(bind, checkfirst=True)
