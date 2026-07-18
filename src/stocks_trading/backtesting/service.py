from stocks_trading.backtesting.evaluator import run_backtest
from stocks_trading.domain.models import BacktestRunResult, BacktestRunStatus


class BacktestService:
    def __init__(self, repository, configuration):
        self.repository = repository
        self.configuration = configuration

    def run(self, *, start_date, end_date):
        if not self.configuration.enabled:
            raise ValueError("backtest configuration is disabled")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        signals, candles = self.repository.load_sources(
            self.configuration.strategy_name, self.configuration.strategy_version,
            self.configuration.strategy_config_checksum, start_date, end_date,
        )
        result = run_backtest(signals, candles, self.configuration)
        run_id = self.repository.save_run(self.configuration, start_date, end_date, result)
        return BacktestRunResult(run_id, BacktestRunStatus.SUCCEEDED, result.aggregate)
