import csv
from datetime import date
from pathlib import Path


def main() -> None:
    source = Path("/tmp/indonesia.csv")
    destination = Path("data/universe/idx_2025-09-20.csv")
    if not source.exists():
        raise SystemExit("download indonesia.csv to /tmp before running")

    with source.open(encoding="utf-8-sig", newline="") as input_file:
        rows = list(csv.DictReader(input_file))

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=[
                "snapshot_date",
                "symbol",
                "idx_code",
                "issuer_name",
                "board",
                "sector",
            ],
        )
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["ticker"]):
            ticker = row["ticker"].strip().upper()
            writer.writerow(
                {
                    "snapshot_date": date(2025, 9, 20).isoformat(),
                    "symbol": f"{ticker}.JK",
                    "idx_code": ticker,
                    "issuer_name": row["name"].strip(),
                    "board": "",
                    "sector": row["sector"].strip(),
                }
            )


if __name__ == "__main__":
    main()
