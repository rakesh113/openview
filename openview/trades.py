"""Normalize backtest trade logs.

Canonical columns (header required):

    symbol,side,entry_time,entry_price,exit_time,exit_price,quantity,pnl,tag

`symbol`, `side`, `entry_time`, and `entry_price` are required. `symbol` may be
omitted when the upload supplies a default symbol. Times are ISO-8601;
timezone-naive values are read as Asia/Kolkata. Existing logs that use
`Type`, `Entry Time`, `Entry Price`, `Exit Time`, `Exit Price`, `PnL`, and
`Reason` are accepted without renaming.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_MAX_BYTES = 5_000_000
_MAX_ROWS = 50_000

_HEADER_ALIASES = {
    "symbol": "symbol",
    "ticker": "symbol",
    "tradingsymbol": "symbol",
    "side": "side",
    "type": "side",
    "direction": "side",
    "entry_time": "entry_time",
    "entrytime": "entry_time",
    "exit_time": "exit_time",
    "exittime": "exit_time",
    "entry_price": "entry_price",
    "entryprice": "entry_price",
    "exit_price": "exit_price",
    "exitprice": "exit_price",
    "quantity": "quantity",
    "qty": "quantity",
    "shares": "quantity",
    "pnl": "pnl",
    "p_l": "pnl",
    "profit": "pnl",
    "net_pnl": "pnl",
    "tag": "tag",
    "strategy": "tag",
    "reason": "tag",
    "note": "tag",
    "result": "result",
    "return_pct": "return_pct",
    "returnpct": "return_pct",
}

_LONG = {"long", "buy", "b", "l"}
_SHORT = {"short", "sell", "s"}


def trade_spec() -> dict:
    return {
        "description": "Round-trip backtest trades. One row is one completed or open position.",
        "required": ["symbol", "side", "entry_time", "entry_price"],
        "optional": ["exit_time", "exit_price", "quantity", "pnl", "tag"],
        "symbol_optional_when": "a default symbol is selected in the upload dialog",
        "time_format": "ISO-8601. Naive timestamps are interpreted as Asia/Kolkata.",
        "side_values": ["long", "short"],
        "aliases": {
            "symbol": ["ticker", "tradingsymbol"],
            "side": ["type", "direction"],
            "entry_time": ["Entry Time"],
            "entry_price": ["Entry Price"],
            "exit_time": ["Exit Time"],
            "exit_price": ["Exit Price"],
            "quantity": ["qty", "shares"],
            "pnl": ["PnL", "profit"],
            "tag": ["strategy", "reason", "note"],
        },
        "example": (
            "symbol,side,entry_time,entry_price,exit_time,exit_price,quantity,pnl,tag\n"
            "RELIANCE,long,2024-01-15T09:45:00+05:30,2488.50,2024-01-15T11:15:00+05:30,2506.20,100,1770.00,orb\n"
            "RELIANCE,short,2024-01-16T10:05:00+05:30,2510.00,2024-01-16T13:20:00+05:30,2494.75,50,762.50,vwap\n"
        ),
    }


def _header_key(value: str) -> str:
    cleaned = value.lstrip("\ufeff").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return _HEADER_ALIASES.get(cleaned, cleaned)


def _blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _parse_time(value: str) -> int:
    text = value.strip()
    if re.fullmatch(r"\d{10}", text):
        return int(text)
    if re.fullmatch(r"\d{13}", text):
        return int(text) // 1000
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"unrecognized time {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return int(parsed.astimezone(timezone.utc).timestamp())


def _parse_float(value: str, field: str) -> float:
    text = value.strip().replace(",", "")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"invalid {field} {value!r}") from exc


def _parse_side(value: str) -> str:
    key = value.strip().lower()
    if key in _LONG:
        return "long"
    if key in _SHORT:
        return "short"
    raise ValueError(f"side must be long or short (got {value!r})")


def parse_trade_csv(text: str, default_symbol: str | None = None) -> dict:
    if len(text.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("CSV is larger than 5 MB")
    sample = text.lstrip("\ufeff")
    if not sample.strip():
        raise ValueError("CSV is empty")
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        raise ValueError("CSV needs a header row")
    field_map = {_header_key(name): name for name in reader.fieldnames if name}
    required = ["side", "entry_time", "entry_price"]
    if "symbol" not in field_map and not (default_symbol and default_symbol.strip()):
        required.append("symbol")
    missing = [name for name in required if name not in field_map]
    if missing:
        raise ValueError(
            "Missing column(s): "
            + ", ".join(missing)
            + ". Expected symbol, side, entry_time, entry_price "
            + "(aliases such as Type, Entry Time, and Entry Price are fine)."
        )

    fallback = default_symbol.strip().upper() if default_symbol and default_symbol.strip() else None
    trades: list[dict] = []
    errors: list[str] = []
    for index, row in enumerate(reader, start=2):
        if len(trades) >= _MAX_ROWS:
            errors.append(f"Stopped after {_MAX_ROWS} trades")
            break
        if row is None or all(_blank(value) for value in row.values()):
            continue
        try:
            raw_symbol = row.get(field_map["symbol"]) if "symbol" in field_map else None
            symbol = (raw_symbol or "").strip().upper() or fallback
            if not symbol:
                raise ValueError("symbol is empty")
            side = _parse_side(row[field_map["side"]] or "")
            entry_time = _parse_time(row[field_map["entry_time"]] or "")
            entry_price = _parse_float(row[field_map["entry_price"]] or "", "entry_price")
            exit_time = None
            exit_price = None
            if "exit_time" in field_map and not _blank(row.get(field_map["exit_time"])):
                exit_time = _parse_time(row[field_map["exit_time"]] or "")
            if "exit_price" in field_map and not _blank(row.get(field_map["exit_price"])):
                exit_price = _parse_float(row[field_map["exit_price"]] or "", "exit_price")
            quantity = None
            if "quantity" in field_map and not _blank(row.get(field_map["quantity"])):
                quantity = _parse_float(row[field_map["quantity"]] or "", "quantity")
            pnl = None
            if "pnl" in field_map and not _blank(row.get(field_map["pnl"])):
                pnl = _parse_float(row[field_map["pnl"]] or "", "pnl")
            tag = None
            if "tag" in field_map and not _blank(row.get(field_map["tag"])):
                tag = (row[field_map["tag"]] or "").strip() or None
            if exit_time is not None and exit_time < entry_time:
                raise ValueError("exit_time is before entry_time")
            trades.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "exit_time": exit_time,
                    "exit_price": exit_price,
                    "quantity": quantity,
                    "pnl": pnl,
                    "tag": tag,
                }
            )
        except ValueError as exc:
            errors.append(f"row {index}: {exc}")
    trades.sort(key=lambda item: (item["entry_time"], item["symbol"]))
    return {"trades": trades, "errors": errors, "count": len(trades)}
