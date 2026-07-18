"""Create technical-v2 liquidity indicator and rule engine tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0003"
down_revision: str | None = "20260716_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

rule_run_mode = postgresql.ENUM(
    "rebuild", "update", name="rule_run_mode", create_type=False
)
rule_run_status = postgresql.ENUM(
    "running",
    "succeeded",
    "partial_failure",
    "failed",
    name="rule_run_status",
    create_type=False,
)
rule_symbol_status = postgresql.ENUM(
    "success", "no_data", "failed", name="rule_symbol_status", create_type=False
)


def upgrade() -> None:
    op.add_column(
        "daily_indicators",
        sa.Column("average_traded_value_20", sa.Numeric(30, 6)),
    )
    bind = op.get_bind()
    rule_run_mode.create(bind, checkfirst=True)
    rule_run_status.create(bind, checkfirst=True)
    rule_symbol_status.create(bind, checkfirst=True)
    op.create_table(
        "daily_rules",
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
        sa.Column("formula_version", sa.String(64), nullable=False),
        sa.Column("config_checksum", sa.String(64), nullable=False),
        sa.Column("indicator_version", sa.String(64), nullable=False),
        sa.Column("price_above_ma5", sa.Boolean()),
        sa.Column("price_above_ma10", sa.Boolean()),
        sa.Column("price_above_ma20", sa.Boolean()),
        sa.Column("ma5_above_ma10", sa.Boolean()),
        sa.Column("ma10_above_ma20", sa.Boolean()),
        sa.Column("volume_spike", sa.Boolean()),
        sa.Column("breakout_20", sa.Boolean()),
        sa.Column("high_liquidity", sa.Boolean()),
        sa.Column("positive_momentum", sa.Boolean()),
        sa.Column("candle_updated_at", sa.DateTime(timezone=True)),
        sa.Column("indicator_calculated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "security_id",
            "provider",
            "interval",
            "trading_date",
            "formula_version",
            "config_checksum",
            name="uq_daily_rule_identity",
        ),
    )
    op.create_index(
        "ix_daily_rules_security_date", "daily_rules", ["security_id", "trading_date"]
    )
    op.create_table(
        "rule_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", rule_run_mode, nullable=False),
        sa.Column("status", rule_run_status, nullable=False),
        sa.Column("formula_version", sa.String(64), nullable=False),
        sa.Column("config_checksum", sa.String(64), nullable=False),
        sa.Column("indicator_version", sa.String(64), nullable=False),
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
        "rule_symbol_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rule_runs.id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", rule_symbol_status, nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "symbol", name="uq_rule_run_symbol"),
    )


def downgrade() -> None:
    op.drop_table("rule_symbol_results")
    op.drop_table("rule_runs")
    op.drop_index("ix_daily_rules_security_date", table_name="daily_rules")
    op.drop_table("daily_rules")
    op.drop_column("daily_indicators", "average_traded_value_20")
    bind = op.get_bind()
    rule_symbol_status.drop(bind, checkfirst=True)
    rule_run_status.drop(bind, checkfirst=True)
    rule_run_mode.drop(bind, checkfirst=True)
