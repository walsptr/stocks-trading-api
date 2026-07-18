"""Create durable Telegram alert tables."""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "20260716_0008"
down_revision: str | None = "20260716_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    bind = op.get_bind()
    for enum in (
        postgresql.ENUM("pending", "sent", "failed", name="alert_delivery_status"),
        postgresql.ENUM("rebuild", "update", "retry", name="alert_run_mode"),
        postgresql.ENUM("running", "succeeded", "partial_failure", "failed", name="alert_run_status"),
    ):
        enum.create(bind, checkfirst=True)
    op.create_table("alert_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False), sa.Column("alert_version", sa.String(64), nullable=False),
        sa.Column("alert_config_checksum", sa.String(64), nullable=False), sa.Column("triggers", postgresql.JSONB(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False), sa.Column("current_score", sa.Integer(), nullable=False),
        sa.Column("previous_score", sa.Integer()), sa.Column("current_rating", sa.String(32), nullable=False),
        sa.Column("previous_rating", sa.String(32)), sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("strategy_status", sa.String(16), nullable=False), sa.Column("bullish_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("caution_reasons", postgresql.JSONB(), nullable=False), sa.Column("source_versions", postgresql.JSONB(), nullable=False),
        sa.Column("delivery_status", postgresql.ENUM("pending", "sent", "failed", name="alert_delivery_status", create_type=False), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False), sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("symbol", "trading_date", "alert_version", "alert_config_checksum", name="uq_alert_event_identity"))
    op.create_index("ix_alert_events_date_status", "alert_events", ["trading_date", "delivery_status"])
    op.create_table("alert_delivery_attempts", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("alert_events.id"), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False), sa.Column("error", sa.Text()),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("alert_watermarks", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_version", sa.String(64), nullable=False), sa.Column("alert_config_checksum", sa.String(64), nullable=False),
        sa.Column("last_processed_date", sa.Date(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("alert_runs", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", postgresql.ENUM("rebuild", "update", "retry", name="alert_run_mode", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM("running", "succeeded", "partial_failure", "failed", name="alert_run_status", create_type=False), nullable=False),
        sa.Column("generated_count", sa.Integer(), nullable=False), sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)))

def downgrade() -> None:
    op.drop_table("alert_runs"); op.drop_table("alert_watermarks"); op.drop_table("alert_delivery_attempts")
    op.drop_index("ix_alert_events_date_status", table_name="alert_events"); op.drop_table("alert_events")
    bind = op.get_bind()
    for name in ("alert_run_status", "alert_run_mode", "alert_delivery_status"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
