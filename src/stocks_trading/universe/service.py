import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from stocks_trading.domain.models import Security
from stocks_trading.domain.ports import UniverseRepository

REQUIRED_COLUMNS = {"snapshot_date", "symbol", "idx_code", "issuer_name"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{4,12}\.JK$")
IDX_CODE_PATTERN = re.compile(r"^[A-Z0-9]{4,12}$")


@dataclass(frozen=True, slots=True)
class UniverseImportResult:
    snapshot_date: date
    checksum: str
    total: int
    inserted: int
    updated: int
    marked_inactive: int


class UniverseCsvError(ValueError):
    pass


class UniverseService:
    def __init__(self, repository: UniverseRepository) -> None:
        self.repository = repository

    def import_csv(self, path: Path) -> UniverseImportResult:
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        snapshot_date, securities = parse_universe_csv(content.decode("utf-8-sig"))
        inserted, updated, marked_inactive = self.repository.import_snapshot(
            snapshot_date=snapshot_date,
            checksum=checksum,
            source=str(path),
            securities=securities,
        )
        return UniverseImportResult(
            snapshot_date=snapshot_date,
            checksum=checksum,
            total=len(securities),
            inserted=inserted,
            updated=updated,
            marked_inactive=marked_inactive,
        )


def parse_universe_csv(content: str) -> tuple[date, list[Security]]:
    reader = csv.DictReader(content.splitlines())
    if reader.fieldnames is None:
        raise UniverseCsvError("CSV header is required")
    missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing_columns:
        raise UniverseCsvError(
            f"missing required columns: {', '.join(sorted(missing_columns))}"
        )

    securities: list[Security] = []
    symbols: set[str] = set()
    idx_codes: set[str] = set()
    snapshot_dates: set[date] = set()
    errors: list[str] = []

    for row_number, row in enumerate(reader, start=2):
        try:
            snapshot_date = date.fromisoformat(required_value(row, "snapshot_date"))
            symbol = required_value(row, "symbol").upper()
            idx_code = required_value(row, "idx_code").upper()
            issuer_name = required_value(row, "issuer_name")
            board = optional_value(row, "board")
            sector = optional_value(row, "sector")

            if not SYMBOL_PATTERN.fullmatch(symbol):
                raise UniverseCsvError("symbol must be uppercase and end in .JK")
            if not IDX_CODE_PATTERN.fullmatch(idx_code):
                raise UniverseCsvError("idx_code must be 4-12 uppercase letters/digits")
            if symbol != f"{idx_code}.JK":
                raise UniverseCsvError("symbol must equal idx_code plus .JK")
            if symbol in symbols:
                raise UniverseCsvError(f"duplicate symbol {symbol}")
            if idx_code in idx_codes:
                raise UniverseCsvError(f"duplicate idx_code {idx_code}")

            symbols.add(symbol)
            idx_codes.add(idx_code)
            snapshot_dates.add(snapshot_date)
            securities.append(
                Security(
                    symbol=symbol,
                    idx_code=idx_code,
                    issuer_name=issuer_name,
                    board=board,
                    sector=sector,
                )
            )
        except (UniverseCsvError, ValueError) as error:
            errors.append(f"row {row_number}: {error}")

    if errors:
        raise UniverseCsvError("; ".join(errors[:20]))
    if not securities:
        raise UniverseCsvError("CSV contains no securities")
    if len(snapshot_dates) != 1:
        raise UniverseCsvError("all rows must use the same snapshot_date")
    return snapshot_dates.pop(), securities


def required_value(row: dict[str, str | None], name: str) -> str:
    value = row.get(name)
    if value is None or not value.strip():
        raise UniverseCsvError(f"{name} is required")
    return value.strip()


def optional_value(row: dict[str, str | None], name: str) -> str | None:
    value = row.get(name)
    return value.strip() if value and value.strip() else None

