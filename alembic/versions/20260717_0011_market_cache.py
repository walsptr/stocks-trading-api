"""Add explicit market refresh collection command."""
from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0011"
down_revision: str | None = "20260717_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE run_command ADD VALUE IF NOT EXISTS 'refresh'")


def downgrade() -> None:
    pass
