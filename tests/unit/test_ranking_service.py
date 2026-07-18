from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from stocks_trading.config.settings import Settings
from stocks_trading.domain.models import RankingDateStatus, TechnicalScore
from stocks_trading.ranking.config import load_ranking_configuration
from stocks_trading.ranking.service import RankingService


class FakeRankingRepository:
    def __init__(self, *, fail_date=None, dates=None):
        self.fail_date = fail_date
        self.dates = dates
        self.replacements = []
        self.date_calls = []

    def source_score_dates(self, version, checksum, *, start_date, end_date):
        self.date_calls.append((version, checksum, start_date, end_date))
        return self.dates if self.dates is not None else [date(2026, 7, 15), date(2026, 7, 16)]

    def load_scores_for_date(self, trading_date, version, checksum):
        if trading_date == self.fail_date:
            raise RuntimeError("broken source")
        if self.dates == []:
            return []
        return [(technical_score("BBCA.JK", trading_date, version, checksum), None)]

    def latest_ranking_date(self, version, checksum):
        return date(2026, 7, 10)

    def replace_rankings(self, trading_date, version, checksum, rankings):
        self.replacements.append((trading_date, tuple(rankings)))
        return len(rankings)


class FakeRunRepository:
    def __init__(self):
        self.run_id = uuid4()
        self.results = []

    def create_ranking_run(self, request):
        self.request = request
        return self.run_id

    def record_ranking_date_result(self, run_id, result):
        self.results.append(result)

    def finish_ranking_run(self, run_id):
        self.finished = run_id

    def abandon_ranking_run(self, run_id):
        self.abandoned = run_id


def technical_score(symbol, trading_date, version, checksum):
    return TechnicalScore(
        symbol=symbol,
        trading_date=trading_date,
        scoring_version=version,
        scoring_config_checksum=checksum,
        score=90,
        rating="Strong Buy",
        contributions={},
        source_rule_formula_version="rules-v1",
        source_rule_config_checksum="rules-checksum",
    )


def service(repository):
    return RankingService(
        ranking_repository=repository,
        run_repository=FakeRunRepository(),
        settings=Settings(database_url="postgresql+psycopg://unused"),
        configuration=load_ranking_configuration(Path("config/ranking/technical-v1.yaml")),
    )


@pytest.mark.asyncio
async def test_update_uses_seven_day_overlap() -> None:
    repository = FakeRankingRepository()
    result = await service(repository).update(as_of=date(2026, 7, 16))
    assert result.failed_count == 0
    assert repository.date_calls[0][2] == date(2026, 7, 3)
    assert len(repository.replacements) == 2


@pytest.mark.asyncio
async def test_date_failure_is_isolated() -> None:
    repository = FakeRankingRepository(fail_date=date(2026, 7, 16))
    result = await service(repository).rebuild()
    assert result.failed_count == 1
    assert {item.status for item in result.dates} == {
        RankingDateStatus.SUCCESS,
        RankingDateStatus.FAILED,
    }


@pytest.mark.asyncio
async def test_explicit_date_without_scores_records_no_data() -> None:
    repository = FakeRankingRepository(dates=[])
    result = await service(repository).rebuild(
        start_date=date(2026, 7, 16), end_date=date(2026, 7, 16)
    )
    assert result.dates[0].status == RankingDateStatus.NO_DATA
