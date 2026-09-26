"""Find the candle table in a DuckDB or MotherDuck database."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from openview.config import IDENT, ColumnOverride

_IDENT_RE = re.compile(IDENT)

TIME_PREFERENCE = (
    "timestamp",
    "datetime",
    "ts",
    "bartime",
    "candletime",
    "tradedat",
    "time",
    "date",
)
SYMBOL_PREFERENCE = (
    "symbol",
    "tradingsymbol",
    "ticker",
    "instrument",
    "symbolname",
    "scrip",
)
OPEN_PREFERENCE = ("open", "openprice", "o")
HIGH_PREFERENCE = ("high", "highprice", "h")
LOW_PREFERENCE = ("low", "lowprice", "l")
CLOSE_PREFERENCE = ("close", "closeprice", "ltp", "c")
VOLUME_PREFERENCE = ("volume", "vol", "volumetraded", "tottrdqty", "qty", "v")

NUMERIC_HINTS = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC", "HUGEINT")
NAME_HINTS = (
    ("candle", 50),
    ("ohlc", 45),
    ("ohlcv", 45),
    ("bar", 18),
    ("minute", 16),
    ("equity", 12),
    ("spot", 10),
    ("price", 8),
)


@dataclass
class CandleSchema:
    schema: str
    table: str
    symbol: str
    time: str
    open: str
    high: str
    low: str
    close: str
    volume: str | None
    # timestamptz | exchange | utc | date
    time_kind: str
    estimated_rows: int | None = None
    key_column: str | None = None
    price_divisor: float = 1.0
    interval_column: str | None = None
    native_intervals: dict[str, str] | None = None

    @property
    def qualified_name(self) -> str:
        return f"{quote_ident(self.schema)}.{quote_ident(self.table)}"

    @property
    def filter_column(self) -> str:
        return self.key_column or self.symbol


def quote_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Refusing to interpolate identifier {name!r}")
    return f'"{name}"'


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _time_kind(data_type: str) -> str | None:
    upper = data_type.upper()
    if "WITH TIME ZONE" in upper or "TIMESTAMPTZ" in upper:
        return "timestamptz"
    if upper.startswith("TIMESTAMP") or "TIMESTAMP" in upper:
        return "timestamp"
    if upper.startswith("DATE") or upper == "DATE":
        return "date"
    return None


def _is_numeric(data_type: str) -> bool:
    upper = data_type.upper()
    return any(hint in upper for hint in NUMERIC_HINTS)


def _pick(columns: dict[str, tuple[str, str]], preference: tuple[str, ...]) -> tuple[str, str] | None:
    """Return (original_name, data_type) for the best preference hit."""
    by_norm = {_norm(name): (name, dtype) for name, dtype in columns.values()}
    for candidate in preference:
        if candidate in by_norm:
            return by_norm[candidate]
    return None


def match_columns(columns: list[tuple[str, str]]) -> dict | None:
    """Return a mapping when the column set looks like OHLCV candles."""
    indexed = {name: (name, dtype) for name, dtype in columns}
    symbol = _pick(indexed, SYMBOL_PREFERENCE)
    time = _pick(indexed, TIME_PREFERENCE)
    open_ = _pick(indexed, OPEN_PREFERENCE)
    high = _pick(indexed, HIGH_PREFERENCE)
    low = _pick(indexed, LOW_PREFERENCE)
    close = _pick(indexed, CLOSE_PREFERENCE)
    volume = _pick(indexed, VOLUME_PREFERENCE)
    if not all((symbol, time, open_, high, low, close)):
        return None
    assert symbol and time and open_ and high and low and close
    kind = _time_kind(time[1])
    if kind is None:
        return None
    if not all(_is_numeric(col[1]) for col in (open_, high, low, close)):
        return None
    if volume is not None and not _is_numeric(volume[1]):
        volume = None
    return {
        "symbol": symbol[0],
        "time": time[0],
        "open": open_[0],
        "high": high[0],
        "low": low[0],
        "close": close[0],
        "volume": volume[0] if volume else None,
        "time_kind": kind,
    }


def _name_score(table: str) -> int:
    lowered = table.lower()
    return sum(weight for token, weight in NAME_HINTS if token in lowered)


def _apply_override(columns: list[tuple[str, str]], override: ColumnOverride, stored_as: str | None) -> dict:
    by_norm = {_norm(name): (name, dtype) for name, dtype in columns}
    resolved: dict[str, str | None] = {}
    for key in ("symbol", "time", "open", "high", "low", "close", "volume", "key"):
        wanted = getattr(override, key)
        if not wanted:
            resolved[key] = None
            continue
        found = by_norm.get(_norm(wanted))
        if found is None:
            raise ValueError(f"Column {wanted!r} was not found on the configured table")
        resolved[key] = found[0]
        if key == "time":
            kind = _time_kind(found[1]) or "timestamp"
            resolved["time_dtype"] = found[1]
            resolved["time_kind"] = stored_as or ("exchange" if kind == "timestamp" else kind)
    required = ["time", "open", "high", "low", "close"]
    if not resolved.get("key"):
        required.append("symbol")
    missing = [key for key in required if not resolved.get(key)]
    if missing:
        raise ValueError(f"Column override is missing {', '.join(missing)}")
    if "time_kind" not in resolved:
        resolved["time_kind"] = stored_as or "timestamptz"
    return resolved


def list_tables(con) -> list[dict]:
    rows = con.execute(
        """
        SELECT schema_name, table_name, column_name, data_type
        FROM duckdb_columns()
        WHERE NOT coalesce(internal, false)
          AND schema_name NOT IN ('information_schema', 'pg_catalog')
        ORDER BY schema_name, table_name, column_index
        """
    ).fetchall()
    grouped: dict[tuple[str, str], list[dict]] = {}
    for schema, table, column, dtype in rows:
        if schema.startswith("pg_") or table.startswith("duckdb_"):
            continue
        grouped.setdefault((schema, table), []).append({"name": column, "type": dtype})
    described = [
        {"schema": schema, "table": table, "columns": cols}
        for (schema, table), cols in grouped.items()
    ]
    described.sort(key=lambda item: (item["schema"], item["table"]))
    return described


def _named_column(columns: list[tuple[str, str]], wanted: str | None) -> str | None:
    if not wanted:
        return None
    by_norm = {_norm(name): name for name, _dtype in columns}
    found = by_norm.get(_norm(wanted))
    if found is None:
        raise ValueError(f"Column {wanted!r} was not found on the configured table")
    return found


def _schema_from_map(chosen: dict, mapped: dict, estimate: int | None, interval_column: str | None, pairs: list[tuple[str, str]]) -> CandleSchema:
    return CandleSchema(
        schema=chosen["schema"],
        table=chosen["table"],
        symbol=mapped.get("symbol") or "",
        time=mapped["time"],
        open=mapped["open"],
        high=mapped["high"],
        low=mapped["low"],
        close=mapped["close"],
        volume=mapped.get("volume"),
        time_kind=mapped["time_kind"],
        estimated_rows=estimate,
        key_column=mapped.get("key"),
        interval_column=_named_column(pairs, interval_column),
    )


def detect_candles(
    con,
    *,
    table: str | None = None,
    columns: ColumnOverride | None = None,
    time_stored_as: str | None = None,
    interval_column: str | None = None,
) -> CandleSchema:
    described = list_tables(con)
    sizes: dict[tuple[str, str], int] = {}
    for schema, name, estimate in con.execute(
        """
        SELECT schema_name, table_name, estimated_size
        FROM duckdb_tables()
        WHERE NOT coalesce(internal, false)
        """
    ).fetchall():
        sizes[(schema, name)] = int(estimate or 0)

    if table:
        wanted = _norm(table)
        matches = [item for item in described if _norm(item["table"]) == wanted or f"{_norm(item['schema'])}.{wanted}" == wanted]
        if not matches:
            known = ", ".join(f"{item['schema']}.{item['table']}" for item in described[:20]) or "(none)"
            raise ValueError(f"Table {table!r} was not found. Visible tables: {known}")
        chosen = matches[0]
        pairs = [(col["name"], col["type"]) for col in chosen["columns"]]
        if columns and any(getattr(columns, key) for key in ("symbol", "time", "open", "high", "low", "close")):
            mapped = _apply_override(pairs, columns, time_stored_as)
        else:
            mapped = match_columns(pairs)
            if mapped is None:
                raise ValueError(f"{chosen['schema']}.{chosen['table']} does not look like an OHLC table")
            if time_stored_as:
                mapped["time_kind"] = time_stored_as
            elif mapped["time_kind"] == "timestamp":
                mapped["time_kind"] = "exchange"
        return _schema_from_map(
            chosen,
            mapped,
            sizes.get((chosen["schema"], chosen["table"])),
            interval_column,
            pairs,
        )

    best: CandleSchema | None = None
    best_score = -1e18
    for item in described:
        pairs = [(col["name"], col["type"]) for col in item["columns"]]
        mapped = match_columns(pairs)
        if mapped is None:
            continue
        if time_stored_as:
            mapped["time_kind"] = time_stored_as
        elif mapped["time_kind"] == "timestamp":
            # Naive timestamps in this project are exchange-local (NSE, IST).
            mapped["time_kind"] = "exchange"
        estimate = sizes.get((item["schema"], item["table"]), 0)
        score = _name_score(item["table"]) + math.log10(estimate + 1) * 20
        if score > best_score:
            best_score = score
            best = _schema_from_map(item, mapped, estimate or None, interval_column, pairs)
    if best is None:
        raise ValueError("No OHLC candle table found. Set datasets[].table and datasets[].columns in openview.yaml.")
    return best
