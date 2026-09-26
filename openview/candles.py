"""Resample candles in SQL.

The equity database is about 198 million 1-minute rows. Queries always filter
to one symbol and a time window, aggregate inside DuckDB, and return only the
buckets the chart asked for.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from openview.detect import CandleSchema, quote_ident

TIMEFRAMES: dict[str, int | str] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": "day",
    "1w": "week",
}

# One response is a screen of bars plus a little slack, not a multi-year extract.
DEFAULT_LIMIT = 400
MAX_LIMIT = 2000

_TZ_RE = re.compile(r"^[A-Za-z0-9_+\-/]+$")
_INTERVAL_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _validate_tz(name: str) -> str:
    if not _TZ_RE.match(name):
        raise ValueError(f"Invalid timezone {name!r}")
    return name


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if value < 1:
        raise ValueError("limit must be at least 1")
    return min(value, MAX_LIMIT)


def bars_span(timeframe: str, limit: int, session_seconds: int) -> timedelta:
    """Calendar span wide enough to contain `limit` session bars, including weekends."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe {timeframe}")
    kind = TIMEFRAMES[timeframe]
    if kind == "week":
        return timedelta(days=7 * limit + 14)
    if kind == "day":
        return timedelta(days=int(limit * 7 / 5) + 14)
    width = int(kind)
    bars_per_session = max(int(session_seconds) / width, 1.0)
    sessions = int(math.ceil(limit / bars_per_session)) + 1
    days = int(math.ceil(sessions * 7 / 5)) + 3
    return timedelta(days=max(days, 2))


def _pad(timeframe: str) -> timedelta:
    width = TIMEFRAMES[timeframe]
    if width == "day":
        return timedelta(days=1)
    if width == "week":
        return timedelta(days=7)
    return timedelta(seconds=int(width))


def _ist_expr(schema: CandleSchema) -> str:
    column = quote_ident(schema.time)
    if schema.time_kind == "timestamptz":
        return f"({column} AT TIME ZONE 'Asia/Kolkata')"
    if schema.time_kind == "utc":
        return f"(({column} AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')"
    # Naive exchange-local timestamp, or a DATE promoted to midnight.
    if schema.time_kind == "date":
        return f"CAST({column} AS TIMESTAMP)"
    return column


def _price_expr(schema: CandleSchema, column: str) -> str:
    cast = f"CAST({quote_ident(column)} AS DOUBLE)"
    divisor = float(schema.price_divisor or 1)
    if divisor == 1:
        return cast
    if not math.isfinite(divisor) or divisor <= 0:
        raise ValueError("price_divisor must be a positive number")
    rendered = format(divisor, "f").rstrip("0").rstrip(".") or format(divisor, "f")
    return f"({cast} / {rendered})"


def _volume_expr(schema: CandleSchema) -> str:
    if not schema.volume:
        return "0::DOUBLE"
    return f"CAST({quote_ident(schema.volume)} AS DOUBLE)"


def _query_mode(schema: CandleSchema, timeframe: str) -> str:
    native = schema.native_intervals or {}
    if schema.interval_column and timeframe in native and timeframe in {"1m", "1d"}:
        return "passthrough"
    if schema.interval_column and timeframe == "1w" and "1d" in native:
        return "week_from_daily"
    if schema.time_kind == "date" and timeframe not in {"1d", "1w"}:
        raise ValueError(f"{timeframe} is not available for a date-only table")
    return "resample"


def _interval_sql(schema: CandleSchema, timeframe: str, mode: str) -> str:
    if not schema.interval_column:
        return ""
    native = schema.native_intervals or {}
    if mode == "passthrough":
        raw = native.get(timeframe)
    elif mode == "week_from_daily":
        raw = native.get("1d")
    else:
        raw = native.get("1m")
    if not raw:
        if mode == "resample" and not native:
            return ""
        raise ValueError(f"{timeframe} needs a source interval in native_intervals")
    if not _INTERVAL_RE.match(raw):
        raise ValueError(f"Invalid interval value {raw!r}")
    return f" AND {quote_ident(schema.interval_column)} = '{raw}'"


def _epoch_instant(schema: CandleSchema, expr: str, tz: str) -> str:
    if schema.time_kind == "timestamptz":
        return f"CAST(epoch({expr}) AS BIGINT)"
    if schema.time_kind == "utc":
        return f"CAST(epoch(({expr}) AT TIME ZONE 'UTC') AS BIGINT)"
    if schema.time_kind == "date":
        return f"CAST(epoch(CAST({expr} AS TIMESTAMP) AT TIME ZONE '{tz}') AS BIGINT)"
    return f"CAST(epoch(({expr}) AT TIME ZONE '{tz}') AS BIGINT)"


def _select_prices(schema: CandleSchema) -> str:
    return f"""
        {_price_expr(schema, schema.open)} AS open,
        {_price_expr(schema, schema.high)} AS high,
        {_price_expr(schema, schema.low)} AS low,
        {_price_expr(schema, schema.close)} AS close,
        {_volume_expr(schema)} AS volume
    """


def candle_sql(
    schema: CandleSchema,
    timeframe: str,
    *,
    timezone_name: str,
    session_open_minutes: int,
    session_seconds: int,
    limit: int,
    descending: bool,
) -> str:
    """One symbol, one time window, at most `limit` bars. The caller binds the key and the instants."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe {timeframe}")
    if limit < 1 or limit > MAX_LIMIT + 1:
        raise ValueError("limit is out of range")

    tz = _validate_tz(timezone_name)
    table = schema.qualified_name
    time_col = quote_ident(schema.time)
    ist = _ist_expr(schema)
    mode = _query_mode(schema, timeframe)
    where = (
        f"{quote_ident(schema.filter_column)} = ? AND {time_col} >= ? AND {time_col} < ?"
        f"{_interval_sql(schema, timeframe, mode)}"
    )
    prices = _select_prices(schema)

    if mode == "passthrough":
        inner = f"""
            SELECT
                {_epoch_instant(schema, time_col, tz)} AS t,
                {_price_expr(schema, schema.open)} AS o,
                {_price_expr(schema, schema.high)} AS h,
                {_price_expr(schema, schema.low)} AS l,
                {_price_expr(schema, schema.close)} AS c,
                {_volume_expr(schema)} AS v
            FROM {table}
            WHERE {where}
        """
    elif mode == "week_from_daily" or timeframe in {"1d", "1w"}:
        bucket = "date_trunc('week', ist)" if timeframe == "1w" else "CAST(ist AS DATE)"
        session = ""
        source = "src"
        if mode != "week_from_daily":
            session = f"""
            , sessioned AS (
                SELECT *
                FROM src
                WHERE epoch(ist) - epoch(date_trunc('day', ist) + INTERVAL {int(session_open_minutes)} MINUTE) >= 0
                  AND epoch(ist) - epoch(date_trunc('day', ist) + INTERVAL {int(session_open_minutes)} MINUTE) < {int(session_seconds)}
            )
            """
            source = "sessioned"
        inner = f"""
            WITH src AS (
                SELECT
                    {time_col} AS ts,
                    {ist} AS ist,
                    {prices}
                FROM {table}
                WHERE {where}
            )
            {session}
            SELECT
                CAST(epoch(({bucket})::TIMESTAMP AT TIME ZONE '{tz}') AS BIGINT) AS t,
                CAST(arg_min(open, ts) AS DOUBLE) AS o,
                CAST(max(high) AS DOUBLE) AS h,
                CAST(min(low) AS DOUBLE) AS l,
                CAST(arg_max(close, ts) AS DOUBLE) AS c,
                CAST(coalesce(sum(volume), 0) AS DOUBLE) AS v
            FROM {source}
            GROUP BY 1
        """
    else:
        width = int(TIMEFRAMES[timeframe])
        inner = f"""
            WITH src AS (
                SELECT
                    {time_col} AS ts,
                    {ist} AS ist,
                    {prices}
                FROM {table}
                WHERE {where}
            ),
            marked AS (
                SELECT
                    *,
                    epoch(ist) - epoch(date_trunc('day', ist) + INTERVAL {int(session_open_minutes)} MINUTE) AS secs
                FROM src
            ),
            sessioned AS (
                SELECT
                    ts, open, high, low, close, volume,
                    date_trunc('day', ist) + INTERVAL {int(session_open_minutes)} MINUTE
                        + to_seconds(CAST(floor(secs / {width}) AS BIGINT) * {width}) AS bucket
                FROM marked
                WHERE secs >= 0 AND secs < {int(session_seconds)}
            )
            SELECT
                CAST(epoch(bucket AT TIME ZONE '{tz}') AS BIGINT) AS t,
                CAST(arg_min(open, ts) AS DOUBLE) AS o,
                CAST(max(high) AS DOUBLE) AS h,
                CAST(min(low) AS DOUBLE) AS l,
                CAST(arg_max(close, ts) AS DOUBLE) AS c,
                CAST(coalesce(sum(volume), 0) AS DOUBLE) AS v
            FROM sessioned
            GROUP BY bucket
        """

    direction = "DESC" if descending else "ASC"
    return f"""
        SELECT t, o, h, l, c, v FROM (
            {inner}
        ) ordered
        ORDER BY t {direction}
        LIMIT {int(limit)}
    """


def to_db_param(moment: datetime, time_kind: str) -> datetime:
    """Bind a UTC instant as the type the candle column actually stores."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    utc = moment.astimezone(timezone.utc)
    if time_kind == "timestamptz":
        return utc
    if time_kind == "utc":
        return utc.replace(tzinfo=None)
    # Exchange-local naive timestamp, or a DATE compared as a naive midnight-aware value.
    from zoneinfo import ZoneInfo

    local = utc.astimezone(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    if time_kind == "date":
        return local.date()
    return local


def from_db_value(value, time_kind: str) -> datetime | None:
    if value is None:
        return None
    from zoneinfo import ZoneInfo

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        if time_kind == "utc":
            return value.replace(tzinfo=timezone.utc)
        return value.replace(tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc)
    # datetime.date
    return datetime(value.year, value.month, value.day, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc)


def window_bounds(
    *,
    minimum: datetime,
    maximum: datetime,
    before: int | None,
    after: int | None,
    around: int | None,
    span: timedelta,
) -> tuple[datetime, datetime]:
    if around is not None:
        center = datetime.fromtimestamp(around, tz=timezone.utc)
        start, end = center - span / 2, center + span / 2
    elif before is not None:
        end = datetime.fromtimestamp(before, tz=timezone.utc)
        start = end - span
    elif after is not None:
        start = datetime.fromtimestamp(after, tz=timezone.utc)
        end = start + span
    else:
        end = maximum + timedelta(seconds=1)
        start = end - span
    earliest = minimum - timedelta(days=2)
    latest = maximum + timedelta(days=1)
    if start < earliest:
        start = earliest
    if end > latest:
        end = latest
    if end <= start:
        end = start + timedelta(seconds=1)
    return start, end


def rows_to_bars(rows: list[tuple], *, start: datetime, end: datetime, pad: timedelta) -> list[list]:
    """Keep buckets that overlap the requested window.

    The SQL query is padded by one bucket so a bar cut by the window edge is
    still aggregated from every minute that belongs to it. A weekly bar is
    stamped at Monday 00:00 even when the window starts later in that week, so
    the lower bound has to allow that label through.
    """
    start_epoch = int(start.timestamp())
    end_epoch = int(end.timestamp())
    pad_seconds = max(int(pad.total_seconds()), 1)
    bars: list[list] = []
    for t, o, h, l, c, v in rows:
        if t is None or o is None or h is None or l is None or c is None:
            continue
        ts = int(t)
        if ts >= end_epoch or ts + pad_seconds <= start_epoch:
            continue
        bars.append([ts, round(float(o), 4), round(float(h), 4), round(float(l), 4), round(float(c), 4), int(round(float(v or 0)))])
    return bars
