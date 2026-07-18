from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from stocks_trading.domain.models import PortfolioTransaction, PortfolioTransactionType


class PortfolioValidationError(ValueError):
    pass


class PortfolioService:
    def __init__(self, repository, timezone):
        self.repository = repository
        self.timezone = timezone

    def summary(self):
        return self.repository.summary()

    def transactions(self, limit=10, offset=0):
        return self.repository.transactions(limit=limit, offset=offset), self.repository.count_transactions()

    def create(self, *, transaction_type: str, symbol: str, transaction_date: date,
               quantity: Decimal, price: Decimal, fee: Decimal, notes: str | None = None):
        kind = self._kind(transaction_type)
        symbol = symbol.strip().upper()
        if "." not in symbol:
            symbol += ".JK"
        self._validate_values(symbol, quantity, price, fee)
        if not self.repository.symbol_exists(symbol):
            raise PortfolioValidationError(f"Security {symbol} is not in the active universe")
        projection = self.repository.summary()
        state = next((item for item in projection["holdings"] if item["symbol"] == symbol), None)
        held = Decimal(state["quantity"]) if state else Decimal("0")
        gross = quantity * price
        if kind == PortfolioTransactionType.BUY and gross + fee > Decimal(projection["cash_balance"]):
            raise PortfolioValidationError("Insufficient portfolio cash")
        if kind == PortfolioTransactionType.SELL and quantity > held:
            raise PortfolioValidationError("Sell quantity exceeds current holding")
        transaction = PortfolioTransaction(uuid4(), kind, symbol, transaction_date, quantity, price, fee, notes)
        return self.repository.create_transaction(transaction)

    def reverse(self, transaction_id: UUID, notes: str | None = None):
        original = self.repository.get_transaction(transaction_id)
        if original is None:
            raise PortfolioValidationError("Transaction not found")
        kind = original.transaction_type.value if hasattr(original.transaction_type, "value") else original.transaction_type
        if kind not in {PortfolioTransactionType.BUY.value, PortfolioTransactionType.SELL.value}:
            raise PortfolioValidationError("Only buy or sell transactions can be reversed")
        if self.repository.has_reversal(transaction_id):
            raise PortfolioValidationError("Transaction has already been reversed")
        transaction = PortfolioTransaction(
            uuid4(), PortfolioTransactionType.REVERSAL, original.symbol,
            datetime.now(self.timezone).date(), original.quantity, original.price, -Decimal(str(original.fee)),
            notes or f"Reversal of {original.id}", original.id,
        )
        return self.repository.create_transaction(transaction)

    @staticmethod
    def _kind(value: str) -> PortfolioTransactionType:
        try:
            kind = PortfolioTransactionType(value.lower())
        except ValueError as error:
            raise PortfolioValidationError("transaction_type must be buy or sell") from error
        if kind is PortfolioTransactionType.REVERSAL:
            raise PortfolioValidationError("Use the reversal endpoint for corrections")
        return kind

    @staticmethod
    def _validate_values(symbol, quantity, price, fee):
        if not symbol or not symbol.endswith(".JK"):
            raise PortfolioValidationError("symbol must be an IDX ticker")
        if quantity <= 0:
            raise PortfolioValidationError("quantity must be greater than zero")
        if price <= 0:
            raise PortfolioValidationError("price must be greater than zero")
        if fee < 0:
            raise PortfolioValidationError("fee cannot be negative")
