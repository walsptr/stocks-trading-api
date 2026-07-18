from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from stocks_trading.analysis.config import load_analysis_configuration
from stocks_trading.analysis.service import AnalysisService
from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import AnalysisInput, AnalysisSymbolStatus, DailyRanking


class FakeRepository:
    def __init__(self):
        self.date_calls = []
        self.replacements = []

    def latest_analysis_date(self, version, checksum):
        return date(2026, 7, 10)

    def source_ranking_dates(self, version, checksum, *, start_date, end_date, minimum_score):
        self.date_calls.append((start_date, end_date, minimum_score))
        return [date(2026, 7, 16)]

    def load_analysis_inputs(self, trading_date, *, minimum_score, source_versions):
        return [AnalysisInput(
            ranking=DailyRanking(
                symbol="BBCA.JK", trading_date=trading_date, rank=1, score=90,
                rating="Strong Buy", ranking_version=source_versions["ranking_version"],
                ranking_config_checksum=source_versions["ranking_config_checksum"],
                source_scoring_version=source_versions["scoring_version"],
                source_scoring_config_checksum=source_versions["scoring_config_checksum"],
            ), indicators=None, rules=None, strategy=None,
        )]

    def replace_analyses(self, trading_date, version, checksum, analyses):
        self.replacements.append(tuple(analyses))
        return len(analyses)


class FakeRunRepository:
    def __init__(self):
        self.run_id = uuid4()
        self.results = []

    def create_analysis_run(self, request):
        self.request = request
        return self.run_id

    def record_analysis_symbol_result(self, run_id, result):
        self.results.append(result)

    def finish_analysis_run(self, run_id):
        self.finished = run_id

    def abandon_analysis_run(self, run_id):
        self.abandoned = run_id


def service(repository):
    return AnalysisService(
        analysis_repository=repository, run_repository=FakeRunRepository(),
        settings=Settings(database_url="postgresql+psycopg://unused"),
        configuration=load_analysis_configuration(Path("config/analysis/technical-v1.yaml")),
    )


@pytest.mark.asyncio
async def test_update_uses_overlap_and_writes_snapshot() -> None:
    repository = FakeRepository()
    result = await service(repository).update(as_of=date(2026, 7, 16))
    assert repository.date_calls[0][0] == date(2026, 7, 3)
    assert result.symbols[0].status == AnalysisSymbolStatus.SUCCESS
    assert len(repository.replacements[0]) == 1
