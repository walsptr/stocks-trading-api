"""Add versioned fundamental agent snapshots and runs."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260719_0018"
down_revision: str | None = "20260719_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fundamental_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("config_checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_symbols", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insufficient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "fundamental_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("fundamental_data_as_of", sa.Date(), nullable=False),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("config_checksum", sa.String(64), nullable=False),
        sa.Column("sector", sa.String(128)), sa.Column("industry", sa.String(128)),
        sa.Column("is_bank", sa.Boolean(), nullable=False), sa.Column("latest_report_period", sa.Date()),
        sa.Column("currency", sa.String(16)),
        sa.Column("net_income_latest", sa.Numeric(24,4)), sa.Column("net_income_prior_year", sa.Numeric(24,4)),
        sa.Column("net_income_previous_quarter", sa.Numeric(24,4)), sa.Column("total_debt", sa.Numeric(24,4)),
        sa.Column("stockholders_equity", sa.Numeric(24,4)), sa.Column("roe_percent", sa.Numeric(12,6)),
        sa.Column("der_percent", sa.Numeric(12,6)), sa.Column("trailing_pe", sa.Numeric(20,6)),
        sa.Column("price_to_book", sa.Numeric(20,6)), sa.Column("valuation_per_threshold", sa.Numeric(20,6)),
        sa.Column("valuation_pbv_threshold", sa.Numeric(20,6)), sa.Column("fundamental_score", sa.Numeric(8,4)),
        sa.Column("data_status", sa.String(32), nullable=False), sa.Column("available_core_rules", sa.Integer(), nullable=False),
        sa.Column("applicable_core_rules", sa.Integer(), nullable=False), sa.Column("rule_values", postgresql.JSONB(), nullable=False),
        sa.Column("rule_metadata", postgresql.JSONB(), nullable=False), sa.Column("is_red_flagged", sa.Boolean(), nullable=False),
        sa.Column("red_flag_reasons", postgresql.JSONB(), nullable=False), sa.Column("raw_metrics", postgresql.JSONB(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("security_id", "fundamental_data_as_of", "calculation_version", "config_checksum", name="uq_fundamental_snapshot_identity"),
    )
    op.create_index("ix_fundamental_snapshot_date", "fundamental_snapshots", ["fundamental_data_as_of", "calculation_version"])


def downgrade() -> None:
    op.drop_index("ix_fundamental_snapshot_date", table_name="fundamental_snapshots")
    op.drop_table("fundamental_snapshots")
    op.drop_table("fundamental_runs")
