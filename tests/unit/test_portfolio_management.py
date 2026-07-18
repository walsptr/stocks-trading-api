from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from stocks_trading.domain.models import PortfolioTransactionType
from stocks_trading.persistence.repositories import portfolio_projection
from stocks_trading.portfolio.service import PortfolioService, PortfolioValidationError


def tx(kind, symbol="BBCA.JK", quantity="10", price="100", fee="0", reversal_of_id=None):
    return SimpleNamespace(id=uuid4(), transaction_type=kind, symbol=symbol,
                           quantity=Decimal(quantity), price=Decimal(price), fee=Decimal(fee),
                           transaction_date=date(2026, 7, 18), reversal_of_id=reversal_of_id)


def test_projection_weighted_average_and_realized_pnl():
    first = tx(PortfolioTransactionType.BUY, quantity="10", price="100", fee="10")
    second = tx(PortfolioTransactionType.BUY, quantity="10", price="120", fee="10")
    sell = tx(PortfolioTransactionType.SELL, quantity="5", price="150", fee="5")
    result = portfolio_projection({"id": uuid4(), "initial_cash": Decimal("10000")}, [first, second, sell], {"BBCA.JK": Decimal("140")})
    assert result["cash_balance"] == "8525"
    assert result["realized_pnl"] == "195"
    assert result["holdings"][0]["quantity"] == "15"
    assert result["holdings"][0]["average_price"] == "110"


def test_projection_reversal_is_net_zero():
    buy = tx(PortfolioTransactionType.BUY, quantity="10", price="100", fee="10")
    reversal = tx(PortfolioTransactionType.REVERSAL, quantity="10", price="100", fee="-10", reversal_of_id=buy.id)
    result = portfolio_projection({"id": uuid4(), "initial_cash": Decimal("10000")}, [buy, reversal], {})
    assert result["cash_balance"] == "10000"
    assert result["holdings"] == []


class FakeRepository:
    def __init__(self):
        self.created = []
        self.projection = {"cash_balance": "1000", "holdings": []}
    def symbol_exists(self, symbol): return symbol == "BBCA.JK"
    def summary(self): return self.projection
    def create_transaction(self, transaction): self.created.append(transaction); return {"id": transaction.id}
    def get_transaction(self, transaction_id): return None
    def has_reversal(self, transaction_id): return False


def test_service_rejects_invalid_trade():
    service = PortfolioService(FakeRepository(), __import__("zoneinfo").ZoneInfo("Asia/Jakarta"))
    with pytest.raises(PortfolioValidationError, match="Insufficient"):
        service.create(transaction_type="buy", symbol="BBCA", transaction_date=date.today(), quantity=Decimal("20"), price=Decimal("100"), fee=Decimal("1"))
