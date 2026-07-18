from datetime import date

import pytest

from stocks_trading.universe.service import UniverseCsvError, parse_universe_csv


def test_parse_valid_universe_csv() -> None:
    snapshot_date, securities = parse_universe_csv(
        "snapshot_date,symbol,idx_code,issuer_name,board,sector\n"
        "2026-07-16,BBCA.JK,BBCA,PT Bank Central Asia Tbk,Main,Financials\n"
    )

    assert snapshot_date == date(2026, 7, 16)
    assert securities[0].symbol == "BBCA.JK"
    assert securities[0].sector == "Financials"


@pytest.mark.parametrize(
    "content, message",
    [
        (
            "snapshot_date,symbol,idx_code,issuer_name\n"
            "2026-07-16,BBCA,BBCA,BCA\n",
            "end in .JK",
        ),
        (
            "snapshot_date,symbol,idx_code,issuer_name\n"
            "2026-07-16,BBCA.JK,BBCA,BCA\n"
            "2026-07-16,BBCA.JK,BBCA,BCA duplicate\n",
            "duplicate symbol",
        ),
        (
            "snapshot_date,symbol,idx_code,issuer_name\n"
            "2026-07-16,BBCA.JK,BBCA,BCA\n"
            "2026-07-15,TLKM.JK,TLKM,Telkom\n",
            "same snapshot_date",
        ),
    ],
)
def test_parse_rejects_invalid_csv(content: str, message: str) -> None:
    with pytest.raises(UniverseCsvError, match=message):
        parse_universe_csv(content)

