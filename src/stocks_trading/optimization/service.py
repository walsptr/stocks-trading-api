from stocks_trading.backtesting.config import load_backtest_configuration
from stocks_trading.domain.models import OptimizationRunResult, OptimizationRunStatus
from stocks_trading.optimization.evaluator import optimize


class OptimizationService:
    def __init__(self, repository, configuration):
        self.repository = repository
        self.configuration = configuration
        self.backtest_configuration = load_backtest_configuration(configuration.backtest_config_path)

    def run(self, *, start_date, end_date):
        if not self.configuration.enabled:
            raise ValueError("optimization configuration is disabled")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        sources, candles = self.repository.load_sources(
            self.configuration.indicator_version, start_date, end_date
        )
        result = optimize(sources, candles, self.configuration, self.backtest_configuration)
        run_id = self.repository.save_result(
            self.configuration, self.backtest_configuration.strategy_name,
            start_date, end_date, result,
        )
        return OptimizationRunResult(
            run_id, OptimizationRunStatus.SUCCEEDED,
            len(result.candidates), result.winner_id,
        )
