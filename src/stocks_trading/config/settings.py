from functools import lru_cache
from pathlib import Path
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="STOCKS_",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://stocks:stocks@localhost:5432/stocks"
    timezone: str = "Asia/Jakarta"
    batch_size: int = Field(default=25, ge=1, le=100)
    max_workers: int = Field(default=4, ge=1, le=16)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: float = Field(default=1.0, ge=0)
    incremental_overlap_days: int = Field(default=7, ge=0, le=30)
    log_level: str = "INFO"
    rules_config_path: Path = Path("config/rules-swing-v1.yaml")
    strategies_config_dir: Path = Path("config/strategies")
    scoring_config_path: Path = Path("config/scoring/swing-trend-following-v1.yaml")
    ranking_config_path: Path = Path("config/ranking/technical-v1.yaml")
    analysis_config_path: Path = Path("config/analysis/technical-v1.yaml")
    alerts_config_path: Path = Path("config/alerts/technical-v1.yaml")
    backtest_config_path: Path = Path("config/backtesting/swing-trend-following-v1.yaml")
    optimization_config_path: Path = Path("config/optimization/bsjp-v1.yaml")
    risk_config_path: Path = Path("config/risk/technical-v1.yaml")
    positions_config_path: Path = Path("config/positions/swing-lifecycle-v1.yaml")
    portfolio_initial_cash_idr: Decimal = Field(default=Decimal("100000000"), gt=0)
    cors_origins: str = "http://localhost:21231,http://127.0.0.1:21231"
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Jakarta"
    scheduler_hour: int = Field(default=18, ge=0, le=23)
    scheduler_minute: int = Field(default=0, ge=0, le=59)
    sync_bootstrap_years: int = Field(default=1, ge=1, le=5)
    sync_poll_seconds: float = Field(default=2.0, ge=1, le=30)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def market_timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
