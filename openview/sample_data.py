"""Build a small local DuckDB candle file for demos and tests.

The generated prices are a seeded random walk, not market data. The same seed
writes samples/trades.csv so the sample trades sit on the sample candles.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

IST = ZoneInfo("Asia/Kolkata")
SYMBOLS = {
    "RELIANCE": 2480.0,
    "TCS": 3800.0,
    "INFY": 1550.0,
    "HDFCBANK": 1650.0,
    "ICICIBANK": 990.0,
}
TRADE_DAYS = (8, 22, 41, 63, 90, 120)


def trading_days(count: int, start: datetime | None = None) -> list[datetime]:
    day = start or datetime(2024, 1, 2, tzinfo=IST)
    found: list[datetime] = []
    while len(found) < count:
        if day.weekday() < 5:
            found.append(day)
        day += timedelta(days=1)
    return found


def build_sample(
    path: str | Path,
    *,
    days: int = 160,
    symbols: dict[str, float] | None = None,
    seed: int = 42,
    trades_path: str | Path | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    chosen = symbols or SYMBOLS
    con = duckdb.connect(str(destination))
    con.execute(
        """
        CREATE TABLE candles (
            symbol VARCHAR,
            ts TIMESTAMPTZ,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT
        )
        """
    )
    con.execute("CREATE TABLE notes (id INTEGER, body VARCHAR)")
    con.execute("INSERT INTO notes VALUES (1, 'not a candle table')")

    calendar = trading_days(days)
    trade_rows: list[dict] = []
    batch: list[tuple] = []

    def flush() -> None:
        if not batch:
            return
        con.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        batch.clear()

    for symbol, start_price in chosen.items():
        rng = random.Random(f"{seed}:{symbol}")
        price = start_price
        day_bars: list[tuple] = []
        for day_index, day in enumerate(calendar):
            price *= 1 + rng.gauss(0, 0.004)
            day_bars = []
            for minute in range(375):
                ts = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=minute)
                open_ = price
                shock = rng.gauss(0, 0.0008)
                close = max(1.0, open_ * (1 + shock))
                wick = abs(rng.gauss(0, 0.00035))
                high = max(open_, close) * (1 + wick)
                low = min(open_, close) * (1 - wick)
                session_boost = 1.8 if minute < 20 or minute > 350 else 1.0
                volume = max(1, int(rng.lognormvariate(9.4, 0.35) * session_boost))
                price = close
                row = (symbol, ts, round(open_, 2), round(high, 2), round(low, 2), round(close, 2), volume)
                day_bars.append(row)
                batch.append(row)
                if len(batch) >= 20_000:
                    flush()
            if symbol == "RELIANCE" and day_index in TRADE_DAYS and len(day_bars) > 140:
                side = "long" if (day_index // 8) % 2 == 0 else "short"
                entry = day_bars[25]
                exit_ = day_bars[130]
                quantity = 100 if side == "long" else 50
                if side == "long":
                    pnl = (exit_[5] - entry[2]) * quantity
                else:
                    pnl = (entry[2] - exit_[5]) * quantity
                trade_rows.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "entry_time": entry[1].isoformat(),
                        "entry_price": f"{entry[2]:.2f}",
                        "exit_time": exit_[1].isoformat(),
                        "exit_price": f"{exit_[5]:.2f}",
                        "quantity": quantity,
                        "pnl": f"{pnl:.2f}",
                        "tag": "orb" if side == "long" else "vwap",
                    }
                )
        if symbol == "RELIANCE" and day_bars:
            # 09:15 plus 50 minutes is 10:05 on the last session.
            live = day_bars[50]
            trade_rows.append(
                {
                    "symbol": symbol,
                    "side": "long",
                    "entry_time": live[1].isoformat(),
                    "entry_price": f"{live[2]:.2f}",
                    "exit_time": "",
                    "exit_price": "",
                    "quantity": 25,
                    "pnl": "",
                    "tag": "open",
                }
            )
    flush()
    con.close()

    if trades_path is not None and trade_rows:
        target = Path(trades_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "symbol",
                    "side",
                    "entry_time",
                    "entry_price",
                    "exit_time",
                    "exit_price",
                    "quantity",
                    "pnl",
                    "tag",
                ],
            )
            writer.writeheader()
            writer.writerows(trade_rows)
    return destination


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Create a local sample candle database")
    parser.add_argument("path", nargs="?", default="data/sample.duckdb")
    parser.add_argument("--days", type=int, default=160)
    parser.add_argument("--trades", default="samples/trades.csv")
    args = parser.parse_args()
    built = build_sample(args.path, days=args.days, trades_path=args.trades)
    print(f"Wrote {built} and {args.trades}")


if __name__ == "__main__":
    main()
