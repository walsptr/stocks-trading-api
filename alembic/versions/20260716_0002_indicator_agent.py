"""Create technical indicator tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0002"
down_revision: str | None = "20260716_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

indicator_run_mode = postgresql.ENUM(
    "rebuild", "update", name="indicator_run_mode", create_type=False
)
indicator_run_status = postgresql.ENUM(
    "running",
    "succeeded",
    "partial_failure",
    "failed",
    name="indicator_run_status",
    create_type=False,
)
indicator_symbol_status = postgresql.ENUM(
    "success",
    "no_data",
    "failed",
    name="indicator_symbol_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    indicator_run_mode.create(bind, checkfirst=True)
    indicator_run_status.create(bind, checkfirst=True)
    indicator_symbol_status.create(bind, checkfirst=True)

    op.create_table(
        "daily_indicators",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "security_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("securities.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("sma_5", sa.Numeric(24, 10)),
        sa.Column("sma_10", sa.Numeric(24, 10)),
        sa.Column("sma_20", sa.Numeric(24, 10)),
        sa.Column("sma_50", sa.Numeric(24, 10)),
        sa.Column("sma_200", sa.Numeric(24, 10)),
        sa.Column("volume_ma_20", sa.Numeric(24, 6)),
        sa.Column("volume_ratio", sa.Numeric(24, 10)),
        sa.Column("daily_change_percent", sa.Numeric(24, 10)),
        sa.Column("atr_14", sa.Numeric(24, 10)),
        sa.Column("highest_high_20", sa.Numeric(24, 10)),
        sa.Column("lowest_low_20", sa.Numeric(24, 10)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "security_id",
            "provider",
            "interval",
            "trading_date",
            "calculation_version",
            name="uq_daily_indicator_identity",
        ),
    )
    op.create_index(
        "ix_daily_indicators_security_date",
        "daily_indicators",
        ["security_id", "trading_date"],
    )
    op.create_table(
        "indicator_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", indicator_run_mode, nullable=False),
        sa.Column("status", indicator_run_status, nullable=False),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("requested_start_date", sa.Date()),
        sa.Column("requested_end_date", sa.Date()),
        sa.Column("requested_symbols", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("no_data_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "indicator_symbol_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("indicator_runs.id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", indicator_symbol_status, nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "symbol", name="uq_indicator_run_symbol"),
    )


def downgrade() -> None:
    op.drop_table("indicator_symbol_results")
    op.drop_table("indicator_runs")
    op.drop_index(
        "ix_daily_indicators_security_date", table_name="daily_indicators"
    )
    op.drop_table("daily_indicators")
    bind = op.get_bind()
    indicator_symbol_status.drop(bind, checkfirst=True)
    indicator_run_status.drop(bind, checkfirst=True)
    indicator_run_mode.drop(bind, checkfirst=True)
