"""Create Phase 1 schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

run_command = postgresql.ENUM(
    "bootstrap", "update", "retry", name="run_command", create_type=False
)
run_status = postgresql.ENUM(
    "running",
    "succeeded",
    "partial_failure",
    "failed",
    name="run_status",
    create_type=False,
)
symbol_status = postgresql.ENUM(
    "pending", "success", "no_new_data", "failed", name="symbol_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    run_command.create(bind, checkfirst=True)
    run_status.create(bind, checkfirst=True)
    symbol_status.create(bind, checkfirst=True)

    op.create_table(
        "universe_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False, unique=True),
        sa.Column("source", sa.String(512), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "securities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, unique=True),
        sa.Column("idx_code", sa.String(16), nullable=False, unique=True),
        sa.Column("issuer_name", sa.String(255), nullable=False),
        sa.Column("board", sa.String(64)),
        sa.Column("sector", sa.String(128)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "first_seen_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("universe_snapshots.id"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("universe_snapshots.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "daily_prices",
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
        sa.Column("open", sa.Numeric(20, 6), nullable=False),
        sa.Column("high", sa.Numeric(20, 6), nullable=False),
        sa.Column("low", sa.Numeric(20, 6), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(20, 6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "security_id",
            "provider",
            "interval",
            "trading_date",
            name="uq_daily_price_identity",
        ),
    )
    op.create_index("ix_daily_prices_trading_date", "daily_prices", ["trading_date"])
    op.create_table(
        "collection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command", run_command, nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("requested_start_date", sa.Date(), nullable=False),
        sa.Column("requested_end_date", sa.Date(), nullable=False),
        sa.Column("requested_symbols", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("no_data_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_runs.id"),
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "collection_symbol_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_runs.id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", symbol_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("rows_received", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("run_id", "symbol", name="uq_collection_run_symbol"),
    )


def downgrade() -> None:
    op.drop_table("collection_symbol_results")
    op.drop_table("collection_runs")
    op.drop_index("ix_daily_prices_trading_date", table_name="daily_prices")
    op.drop_table("daily_prices")
    op.drop_table("securities")
    op.drop_table("universe_snapshots")
    bind = op.get_bind()
    symbol_status.drop(bind, checkfirst=True)
    run_status.drop(bind, checkfirst=True)
    run_command.drop(bind, checkfirst=True)
