from collections.abc import Sequence

from stocks_trading.domain.models import DailyRanking, TechnicalScore
from stocks_trading.ranking.config import RankingConfiguration


class RankingEvaluationError(ValueError):
    pass


def rank_scores(
    sources: Sequence[tuple[TechnicalScore, object]],
    configuration: RankingConfiguration,
) -> list[DailyRanking]:
    eligible: list[tuple[TechnicalScore, object]] = []
    trading_date = None
    for score, scored_at in sources:
        if score.scoring_version != configuration.source_scoring_version:
            raise RankingEvaluationError("source scoring version does not match")
        if score.scoring_config_checksum != configuration.source_scoring_config_checksum:
            raise RankingEvaluationError("source scoring configuration checksum does not match")
        if trading_date is None:
            trading_date = score.trading_date
        elif score.trading_date != trading_date:
            raise RankingEvaluationError("source scores must share one trading date")
        if score.score is not None and score.rating is not None:
            eligible.append((score, scored_at))

    eligible.sort(key=lambda item: (-item[0].score, item[0].symbol))
    rankings = []
    previous_score = None
    current_rank = 0
    for position, (score, scored_at) in enumerate(eligible, start=1):
        if score.score != previous_score:
            current_rank = position
            previous_score = score.score
        rankings.append(
            DailyRanking(
                symbol=score.symbol,
                trading_date=score.trading_date,
                rank=current_rank,
                score=score.score,
                rating=score.rating,
                ranking_version=configuration.version,
                ranking_config_checksum=configuration.checksum,
                source_scoring_version=score.scoring_version,
                source_scoring_config_checksum=score.scoring_config_checksum,
                source_scored_at=scored_at,
                provider=score.provider,
                interval=score.interval,
            )
        )
    return rankings
