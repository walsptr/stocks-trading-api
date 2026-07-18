"""Create technical scoring agent tables."""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0005"
down_revision: str | None = "20260716_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

score_run_mode = postgresql.ENUM("rebuild", "update", name="score_run_mode", create_type=False)
score_run_status = postgresql.ENUM("running", "succeeded", "partial_failure", "failed", name="score_run_status", create_type=False)
score_symbol_status = postgresql.ENUM("success", "no_data", "failed", name="score_symbol_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    score_run_mode.create(bind, checkfirst=True)
    score_run_status.create(bind, checkfirst=True)
    score_symbol_status.create(bind, checkfirst=True)
    op.create_table(
        "daily_technical_scores",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("scoring_version", sa.String(64), nullable=False),
        sa.Column("scoring_config_checksum", sa.String(64), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("rating", sa.String(32)),
        sa.Column("contributions", postgresql.JSONB(), nullable=False),
        sa.Column("source_rule_formula_version", sa.String(64), nullable=False),
        sa.Column("source_rule_config_checksum", sa.String(64), nullable=False),
        sa.Column("source_rule_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("security_id", "provider", "interval", "trading_date", "scoring_version", "scoring_config_checksum", name="uq_daily_technical_score_identity"),
    )
    op.create_index("ix_daily_technical_scores_security_date", "daily_technical_scores", ["security_id", "trading_date"])
    op.create_table(
        "score_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", score_run_mode, nullable=False),
        sa.Column("status", score_run_status, nullable=False),
        sa.Column("scoring_version", sa.String(64), nullable=False),
        sa.Column("scoring_config_checksum", sa.String(64), nullable=False),
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
        "score_symbol_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("score_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", score_symbol_status, nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "symbol", name="uq_score_run_symbol"),
    )


def downgrade() -> None:
    op.drop_table("score_symbol_results")
    op.drop_table("score_runs")
    op.drop_index("ix_daily_technical_scores_security_date", table_name="daily_technical_scores")
    op.drop_table("daily_technical_scores")
    bind = op.get_bind()
    score_symbol_status.drop(bind, checkfirst=True)
    score_run_status.drop(bind, checkfirst=True)
    score_run_mode.drop(bind, checkfirst=True)
