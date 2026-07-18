"""Create BSJP optimizer tables."""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "20260717_0010"
down_revision: str | None = "20260716_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    status = postgresql.ENUM("running", "succeeded", "failed", name="optimization_run_status")
    status.create(op.get_bind(), checkfirst=True)
    op.create_table("optimization_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", postgresql.ENUM("running", "succeeded", "failed", name="optimization_run_status", create_type=False), nullable=False),
        sa.Column("optimization_version", sa.String(64), nullable=False), sa.Column("optimization_config_checksum", sa.String(64), nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False), sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("training_start", sa.Date(), nullable=False), sa.Column("training_end", sa.Date(), nullable=False),
        sa.Column("validation_start", sa.Date(), nullable=False), sa.Column("validation_end", sa.Date(), nullable=False),
        sa.Column("winner_id", sa.String(16)), sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_table("optimization_candidates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("optimization_runs.id"), nullable=False),
        sa.Column("candidate_id", sa.String(16), nullable=False), sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False), sa.Column("ineligible_reason", sa.String(64)), sa.Column("rank", sa.Integer()),
        sa.Column("training_metrics", postgresql.JSONB(), nullable=False), sa.Column("validation_metrics", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "candidate_id", name="uq_optimization_candidate"))
    op.create_table("optimization_winner_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("optimization_runs.id"), nullable=False),
        sa.Column("candidate_id", sa.String(16), nullable=False), sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False), sa.Column("exit_date", sa.Date(), nullable=False),
        sa.Column("trade", postgresql.JSONB(), nullable=False))
    op.create_table("optimization_winner_symbols",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("optimization_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False), sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", name="uq_optimization_winner_symbol"))

def downgrade() -> None:
    op.drop_table("optimization_winner_symbols"); op.drop_table("optimization_winner_trades")
    op.drop_table("optimization_candidates"); op.drop_table("optimization_runs")
    postgresql.ENUM(name="optimization_run_status").drop(op.get_bind(), checkfirst=True)
