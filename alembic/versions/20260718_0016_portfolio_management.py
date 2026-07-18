"""Create single-user paper portfolio ledger."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0016"
down_revision: str | None = "20260718_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

portfolio_transaction_type = postgresql.ENUM("buy", "sell", "reversal", name="portfolio_transaction_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    portfolio_transaction_type.create(bind, checkfirst=True)
    op.create_table(
        "portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("initial_cash", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "portfolio_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("transaction_type", portfolio_transaction_type, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.Column("fee", sa.Numeric(20, 6), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("reversal_of_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolio_transactions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("reversal_of_id", name="uq_portfolio_transaction_reversal"),
    )
    op.create_index("ix_portfolio_transactions_date", "portfolio_transactions", ["portfolio_id", "transaction_date", "id"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_transactions_date", table_name="portfolio_transactions")
    op.drop_table("portfolio_transactions")
    op.drop_table("portfolios")
    portfolio_transaction_type.drop(op.get_bind(), checkfirst=True)
