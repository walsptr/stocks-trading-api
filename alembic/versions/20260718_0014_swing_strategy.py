"""Persist Swing Trend Following indicators, rules, and risk targets."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_0014"
down_revision: str | None = "20260718_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, column in (
        ("rsi_14", sa.Numeric(24, 10)),
        ("macd", sa.Numeric(24, 10)),
        ("macd_signal", sa.Numeric(24, 10)),
        ("macd_histogram", sa.Numeric(24, 10)),
        ("macd_bullish_crossover", sa.Boolean()),
        ("higher_low_formed", sa.Boolean()),
    ):
        op.add_column("daily_indicators", sa.Column(name, column))
    for name in (
        "price_above_ma50", "ma20_above_ma50", "ma50_above_ma200",
        "pullback_to_ma20", "rsi_not_overbought", "rsi_not_oversold",
        "macd_bullish_crossover", "higher_low_formed", "volume_confirmation",
        "ma20_below_ma50", "rsi_extreme_overbought",
    ):
        op.add_column("daily_rules", sa.Column(name, sa.Boolean()))
    op.add_column("daily_risk_recommendations", sa.Column("take_profit_1", sa.Numeric(20, 6), nullable=False, server_default="0"))
    op.add_column("daily_risk_recommendations", sa.Column("take_profit_2", sa.Numeric(20, 6), nullable=False, server_default="0"))
    op.add_column("daily_risk_recommendations", sa.Column("suggested_position_size_pct", sa.Numeric(12, 6), nullable=False, server_default="0"))
    op.alter_column("daily_risk_recommendations", "take_profit_1", server_default=None)
    op.alter_column("daily_risk_recommendations", "take_profit_2", server_default=None)
    op.alter_column("daily_risk_recommendations", "suggested_position_size_pct", server_default=None)


def downgrade() -> None:
    for name in ("suggested_position_size_pct", "take_profit_2", "take_profit_1"):
        op.drop_column("daily_risk_recommendations", name)
    for name in (
        "rsi_extreme_overbought", "ma20_below_ma50", "volume_confirmation",
        "higher_low_formed", "macd_bullish_crossover", "rsi_not_oversold",
        "rsi_not_overbought", "pullback_to_ma20", "ma50_above_ma200",
        "ma20_above_ma50", "price_above_ma50",
    ):
        op.drop_column("daily_rules", name)
    for name in ("higher_low_formed", "macd_bullish_crossover", "macd_histogram", "macd_signal", "macd", "rsi_14"):
        op.drop_column("daily_indicators", name)
