"""DuckDB / MotherDuck connections, schema detection, and cached reads."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import duckdb

from openview.candles import (
    TIMEFRAMES,
    bars_span,
    candle_sql,
    clamp_limit,
    from_db_value,
    rows_to_bars,
    to_db_param,
    window_bounds,
)
from openview.config import DatasetConfig, Settings, duckdb_target, resolve_connect
from openview.detect import CandleSchema, detect_candles, list_tables

log = logging.getLogger("openview")

_TOKEN_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}")
_SYMBOL_LIMIT = 2000
_CACHE_SIZE = 64


def public_error(exc: BaseException) -> str:
    message = _TOKEN_RE.sub("[token]", str(exc)).strip()
    return message[:800] or exc.__class__.__name__


class _Cache:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._items: OrderedDict = OrderedDict()

    def get(self, key):
        if key not in self._items:
            return None
        self._items.move_to_end(key)
        return self._items[key]

    def put(self, key, value) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.limit:
            self._items.popitem(last=False)


class Dataset:
    def __init__(self, config: DatasetConfig, settings: Settings) -> None:
        self.config = config
        self.settings = settings
        if config.kind == "duckdb":
            self.connect_target, self.cloud = duckdb_target(config.connect, config.local)
        else:
            self.connect_target = resolve_connect(config.connect)
            self.cloud = False
        self.error: str | None = None
        self.schema: CandleSchema | None = None
        self.inspection: list[dict] = []
        self._con = None
        self._lock = threading.Lock()
        self._symbols: tuple[float, list[str], dict[str, str], bool] | None = None
        self._bounds: dict[str, tuple[float, tuple[datetime, datetime] | None]] = {}
        self._candles = _Cache(_CACHE_SIZE)
        self._keys: dict[str, object] = {}
        self._missing_keys: set[str] = set()

    @property
    def ok(self) -> bool:
        return self.error is None and self.schema is not None

    def open(self) -> None:
        if self._con is not None or self.schema is not None or self.error:
            return
        try:
            if self.config.kind == "http":
                self._open_http()
            elif self.config.kind == "file":
                self._open_file()
            else:
                self._open_duckdb()
            if self.schema is not None:
                self.schema.price_divisor = self.config.price_divisor
                self.schema.native_intervals = dict(self.config.native_intervals)
                self._check_key_mapping()
                log.info(
                    "dataset %s ready: %s (%s)",
                    self.config.id,
                    self.schema.qualified_name,
                    self.config.kind,
                )
        except Exception as exc:  # noqa: BLE001 - surface connection/detection failures to the UI
            self.error = public_error(exc)
            log.warning("dataset %s unavailable: %s", self.config.id, self.error)
            if self._con is not None:
                try:
                    self.inspection = list_tables(self._con)[:40]
                except Exception:  # noqa: BLE001
                    self.inspection = []

    def _check_key_mapping(self) -> None:
        schema = self.schema
        if schema is None:
            return
        if schema.key_column and self.config.symbol_source is None:
            raise ValueError("symbols.table is required when columns.key is set")
        if self.config.symbol_source is not None and not schema.key_column:
            raise ValueError("columns.key is required when symbols.table is set")

    def _open_duckdb(self) -> None:
        target = self.connect_target
        kwargs = {}
        if not self.cloud:
            log.info("dataset %s reading local DuckDB %s", self.config.id, target)
        elif self.config.local:
            log.info(
                "dataset %s local DuckDB not found at %s; using %s",
                self.config.id,
                self.config.local,
                self.config.connect,
            )
        if self.cloud:
            token = os.environ.get(self.settings.token_env, "")
            if not token:
                raise RuntimeError(
                    f"Set {self.settings.token_env} before connecting to {self.config.connect}"
                )
            kwargs["config"] = {"motherduck_token": token}
        # Local files are read-only and carry no username, password, or token.
        self._con = duckdb.connect(target, read_only=not self.cloud, **kwargs)
        self._con.execute("SET TimeZone = 'UTC'")
        self.schema = detect_candles(
            self._con,
            table=self.config.table,
            columns=self.config.columns,
            time_stored_as=self.config.time_stored_as,
            interval_column=self.config.interval_column,
        )

    def _open_file(self) -> None:
        raw_path = self.config.path or self.config.connect
        path = Path(resolve_connect(raw_path))
        if path.suffix.lower() not in {".csv", ".tsv", ".parquet"}:
            raise ValueError("A file source must be .csv, .tsv, or .parquet")
        if not path.is_file():
            raise ValueError(f"Price file not found: {path.name}")
        escaped = str(path).replace("'", "''")
        reader = "read_parquet" if path.suffix.lower() == ".parquet" else "read_csv_auto"
        self._con = duckdb.connect()
        self._con.execute("SET TimeZone = 'UTC'")
        self._con.execute(f"CREATE VIEW candles AS SELECT * FROM {reader}('{escaped}')")
        self.schema = detect_candles(
            self._con,
            table=self.config.table or "candles",
            columns=self.config.columns,
            time_stored_as=self.config.time_stored_as,
            interval_column=self.config.interval_column,
        )

    def _open_http(self) -> None:
        url = self.config.url or ""
        if not (url.startswith("https://") or url.startswith("http://")):
            raise RuntimeError("An http source needs an http(s) URL")
        if not self.config.symbols_url and not self.config.symbol_list:
            raise RuntimeError("An http source needs symbols_url or symbol_list")
        if self.config.symbols_url:
            self._http_json(self.config.symbols_url, {})
        from openview.detect import CandleSchema

        self.schema = CandleSchema(
            schema="http",
            table="candles",
            symbol="symbol",
            time="time",
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            time_kind="timestamptz",
        )

    def _http_json(self, url: str, params: dict) -> object:
        if not (url.startswith("https://") or url.startswith("http://")):
            raise RuntimeError("Price URL must be http(s)")
        query = urlencode({key: value for key, value in params.items() if value is not None and value != ""})
        joiner = "&" if "?" in url else "?"
        target = f"{url}{joiner}{query}" if query else url
        request = Request(target, headers={"Accept": "application/json", "User-Agent": "openview"})
        with urlopen(request, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise RuntimeError("Price response is larger than 2 MB")
        return json.loads(raw.decode("utf-8"))

    def _http_symbols(self, query: str | None) -> dict:
        needle = (query or "").strip()
        if self.config.symbols_url:
            payload = self._http_json(self.config.symbols_url, {"q": needle} if needle else {})
            if isinstance(payload, dict):
                rows = payload.get("symbols", [])
            elif isinstance(payload, list):
                rows = payload
            else:
                rows = []
            names = [str(item) for item in rows if item is not None and str(item) != ""]
        else:
            names = list(self.config.symbol_list)
        if needle:
            folded = needle.upper()
            names = [name for name in names if folded in name.upper()]
            names.sort(key=lambda name: (not name.upper().startswith(folded), len(name), name))
            names = names[:200]
        truncated = not needle and len(names) > _SYMBOL_LIMIT
        if truncated:
            names = []
        return {"symbols": names, "labels": {}, "truncated": truncated, "searched": bool(needle)}

    def _http_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        before: int | None,
        after: int | None,
        around: int | None,
        limit: int | None,
    ) -> dict:
        bar_limit = clamp_limit(limit)
        params = {"symbol": symbol, "timeframe": timeframe, "limit": str(bar_limit)}
        if before is not None:
            params["before"] = str(int(before))
        elif after is not None:
            params["after"] = str(int(after))
        elif around is not None:
            params["around"] = str(int(around))
        bars = _normalize_bars(self._http_json(self.config.url or "", params))[:bar_limit]
        paging_forward = after is not None
        reached_cap = len(bars) >= bar_limit
        has_more = (not paging_forward) and reached_cap
        has_newer = paging_forward and reached_cap
        if around is not None:
            has_more = reached_cap
            has_newer = reached_cap
        return {
            "dataset": self.config.id,
            "symbol": symbol,
            "timeframe": timeframe,
            "timezone": self.settings.timezone,
            "bars": bars,
            "found": bool(bars) or before is not None or after is not None or around is not None,
            "has_more": has_more,
            "next_before": bars[0][0] if has_more and bars else None,
            "has_newer": has_newer,
            "next_after": bars[-1][0] + 1 if has_newer and bars else None,
        }

    def _require(self) -> CandleSchema:
        self.open()
        if self.schema is None or (self.config.kind != "http" and self._con is None):
            raise RuntimeError(self.error or "Dataset is unavailable")
        return self.schema

    def _query(self, sql: str, params: list):
        self._require()
        with self._lock:
            return self._con.execute(sql, params).fetchall()

    def meta(self) -> dict:
        self.open()
        schema = self.schema
        return {
            "id": self.config.id,
            "label": self.config.label,
            "connect": self.config.connect,
            "ok": self.ok,
            "error": self.error,
            "table": f"{schema.schema}.{schema.table}" if schema else None,
            "kind": self.config.kind,
            "columns": (
                {
                    "symbol": schema.symbol
                    or (self.config.symbol_source.column if self.config.symbol_source else "symbol"),
                    "time": schema.time,
                    "open": schema.open,
                    "high": schema.high,
                    "low": schema.low,
                    "close": schema.close,
                    "volume": schema.volume,
                    "time_stored_as": schema.time_kind,
                    "key": schema.key_column,
                    "price_divisor": schema.price_divisor,
                }
                if schema
                else None
            ),
            "estimated_rows": schema.estimated_rows if schema else None,
            "inspection": self.inspection if not self.ok else [],
        }

    def symbols(self, query: str | None = None, refresh: bool = False) -> dict:
        self._require()
        if self.config.kind == "http":
            return self._http_symbols(query)
        if self.config.symbol_source is not None:
            return self._dimension_symbols(query, refresh=refresh)
        schema = self.schema
        assert schema is not None
        column = schema.symbol
        table = schema.qualified_name
        needle = (query or "").strip()
        if needle:
            escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = self._query(
                f"""
                SELECT DISTINCT { _q(column) }
                FROM {table}
                WHERE CAST({ _q(column) } AS VARCHAR) ILIKE ? ESCAPE '\\'
                ORDER BY 1
                LIMIT 200
                """,
                [f"%{escaped}%"],
            )
            names = [str(row[0]) for row in rows if row[0] is not None]
            names.sort(key=lambda name: (not name.upper().startswith(needle.upper()), len(name), name))
            return {"symbols": names, "labels": {}, "truncated": False, "searched": True}

        now = time.monotonic()
        if not refresh and self._symbols and now - self._symbols[0] < 600:
            cached, labels, truncated = self._symbols[1], self._symbols[2], self._symbols[3]
            return {"symbols": cached, "labels": labels, "truncated": truncated, "searched": False}

        rows = self._query(
            f"""
            SELECT DISTINCT { _q(column) }
            FROM {table}
            ORDER BY 1
            LIMIT {_SYMBOL_LIMIT + 1}
            """,
            [],
        )
        names = [str(row[0]) for row in rows if row[0] is not None]
        truncated = len(names) > _SYMBOL_LIMIT
        if truncated:
            names = []
        self._symbols = (now, names, {}, truncated)
        return {"symbols": names, "labels": {}, "truncated": truncated, "searched": False}

    def _dimension_symbols(self, query: str | None, refresh: bool = False) -> dict:
        source = self.config.symbol_source
        assert source is not None
        table = source.qualified_name
        needle = (query or "").strip()
        label_sql = f", {_q(source.label)}" if source.label else ", NULL"
        if needle:
            escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            label_match = f" OR CAST({_q(source.label)} AS VARCHAR) ILIKE ? ESCAPE '\\'" if source.label else ""
            params = [f"%{escaped}%"] * (2 if source.label else 1)
            rows = self._query(
                f"""
                SELECT {_q(source.column)}{label_sql}
                FROM {table}
                WHERE CAST({_q(source.column)} AS VARCHAR) ILIKE ? ESCAPE '\\'{label_match}
                ORDER BY 1
                LIMIT 200
                """,
                params,
            )
            return {**_symbol_payload(rows, needle), "truncated": False, "searched": True}

        now = time.monotonic()
        if not refresh and self._symbols and now - self._symbols[0] < 600:
            cached, labels, truncated = self._symbols[1], self._symbols[2], self._symbols[3]
            return {"symbols": cached, "labels": labels, "truncated": truncated, "searched": False}

        count = int(self._query(f"SELECT count(*) FROM {table}", [])[0][0])
        if count > _SYMBOL_LIMIT:
            self._symbols = (now, [], {}, True)
            return {"symbols": [], "labels": {}, "truncated": True, "searched": False}
        rows = self._query(
            f"SELECT {_q(source.column)}{label_sql} FROM {table} ORDER BY 1",
            [],
        )
        payload = _symbol_payload(rows, "")
        self._symbols = (now, payload["symbols"], payload["labels"], False)
        return {**payload, "truncated": False, "searched": False}

    def _resolve_key(self, symbol: str):
        schema = self.schema
        assert schema is not None
        if not schema.key_column or self.config.symbol_source is None:
            return symbol
        if symbol in self._keys:
            return self._keys[symbol]
        if symbol in self._missing_keys:
            return None
        source = self.config.symbol_source
        rows = self._query(
            f"SELECT {_q(source.key)} FROM {source.qualified_name} WHERE {_q(source.column)} = ? LIMIT 1",
            [symbol],
        )
        if not rows or rows[0][0] is None:
            self._missing_keys.add(symbol)
            return None
        self._keys[symbol] = rows[0][0]
        return rows[0][0]

    def bounds(self, symbol: str) -> tuple[datetime, datetime] | None:
        schema = self._require()
        now = time.monotonic()
        cached = self._bounds.get(symbol)
        if cached and now - cached[0] < 300:
            return cached[1]
        key = self._resolve_key(symbol)
        if key is None:
            self._bounds[symbol] = (now, None)
            return None
        rows = self._query(
            f"SELECT min({_q(schema.time)}), max({_q(schema.time)}) FROM {schema.qualified_name} WHERE {_q(schema.filter_column)} = ?",
            [key],
        )
        minimum = from_db_value(rows[0][0], schema.time_kind) if rows else None
        maximum = from_db_value(rows[0][1], schema.time_kind) if rows else None
        found = None if minimum is None or maximum is None else (minimum, maximum)
        self._bounds[symbol] = (now, found)
        return found

    def previous_time(self, symbol: str, before: datetime) -> datetime | None:
        schema = self._require()
        key = self._resolve_key(symbol)
        if key is None:
            return None
        rows = self._query(
            f"""
            SELECT max({_q(schema.time)})
            FROM {schema.qualified_name}
            WHERE {_q(schema.filter_column)} = ? AND {_q(schema.time)} < ?
            """,
            [key, to_db_param(before, schema.time_kind)],
        )
        if not rows:
            return None
        return from_db_value(rows[0][0], schema.time_kind)

    def candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        before: int | None = None,
        after: int | None = None,
        around: int | None = None,
        limit: int | None = None,
    ) -> dict:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Unknown timeframe {timeframe}")
        schema = self._require()
        if self.config.kind == "http":
            return self._http_candles(symbol, timeframe, before=before, after=after, around=around, limit=limit)
        if schema.time_kind == "date" and timeframe not in {"1d", "1w"}:
            raise ValueError("This table stores dates only. Use the 1D or 1W timeframe.")
        bar_limit = clamp_limit(limit)
        span = self.bounds(symbol)
        empty = {
            "dataset": self.config.id,
            "symbol": symbol,
            "timeframe": timeframe,
            "timezone": self.settings.timezone,
            "bars": [],
            "has_more": False,
            "next_before": None,
            "has_newer": False,
            "next_after": None,
            "found": span is not None,
        }
        if span is None:
            return empty
        key = self._resolve_key(symbol)
        if key is None:
            return empty
        minimum, maximum = span
        start, end = window_bounds(
            minimum=minimum,
            maximum=maximum,
            before=before,
            after=after,
            around=around,
            span=bars_span(timeframe, bar_limit, self.settings.session_seconds),
        )
        cache_key = (symbol, timeframe, int(start.timestamp()), int(end.timestamp()), bar_limit)
        cached = self._candles.get(cache_key)
        if cached is not None:
            return cached

        pad = _pad_for(timeframe)
        descending = after is None and around is None
        sql = candle_sql(
            schema,
            timeframe,
            timezone_name=self.settings.timezone,
            session_open_minutes=self.settings.session_open_minutes,
            session_seconds=self.settings.session_seconds,
            limit=bar_limit + 1,
            descending=descending,
        )
        started = time.perf_counter()
        rows = self._query(
            sql,
            [
                key,
                to_db_param(start - pad, schema.time_kind),
                to_db_param(end + pad, schema.time_kind),
            ],
        )
        more_in_page = len(rows) > bar_limit
        if more_in_page:
            rows = rows[:bar_limit]
        if descending:
            rows = list(reversed(rows))
        bars = rows_to_bars(rows, start=start, end=end, pad=pad)
        if around is not None and len(bars) > bar_limit:
            nearest = sorted(bars, key=lambda bar: abs(bar[0] - around))[:bar_limit]
            bars = sorted(nearest, key=lambda bar: bar[0])
        elapsed = time.perf_counter() - started
        log.info(
            "candles %s %s %s -> %d bars in %.0fms",
            self.config.id,
            symbol,
            timeframe,
            len(bars),
            elapsed * 1000,
        )
        has_more = more_in_page or start > minimum
        has_newer = (after is not None and more_in_page) or end < maximum
        if bars:
            if more_in_page:
                next_before = bars[0][0]
            elif has_more:
                next_before = int(start.timestamp())
            else:
                next_before = None
            if after is not None and more_in_page:
                next_after = bars[-1][0] + 1
            elif has_newer:
                next_after = int(end.timestamp())
            else:
                next_after = None
            payload = {
                **empty,
                "bars": bars,
                "found": True,
                "has_more": has_more,
                "next_before": next_before,
                "has_newer": has_newer,
                "next_after": next_after,
            }
        else:
            previous = self.previous_time(symbol, start) if has_more else None
            payload = {
                **empty,
                "found": True,
                "has_more": previous is not None,
                "next_before": int(previous.timestamp()) + 1 if previous is not None else None,
                "has_newer": has_newer,
                "next_after": int(end.timestamp()) if has_newer else None,
            }
        self._candles.put(cache_key, payload)
        return payload


def _symbol_payload(rows: list[tuple], needle: str) -> dict:
    labels: dict[str, str] = {}
    names: list[str] = []
    for row in rows:
        if row[0] is None:
            continue
        name = str(row[0])
        names.append(name)
        if len(row) > 1 and row[1]:
            labels[name] = str(row[1])
    if needle:
        folded = needle.upper()
        names.sort(key=lambda name: (not name.upper().startswith(folded), len(name), name))
    return {"symbols": names, "labels": labels}


def _normalize_bars(payload) -> list[list]:
    if isinstance(payload, dict):
        rows = payload.get("bars", payload.get("candles", []))
    elif isinstance(payload, list):
        rows = payload
    else:
        raise RuntimeError("Price response must be a list of bars")
    bars: list[list] = []
    for row in rows:
        if isinstance(row, dict):
            stamp = row.get("time", row.get("t"))
            open_ = row.get("open", row.get("o"))
            high = row.get("high", row.get("h"))
            low = row.get("low", row.get("l"))
            close = row.get("close", row.get("c"))
            volume = row.get("volume", row.get("v", 0))
        elif isinstance(row, (list, tuple)) and len(row) >= 5:
            stamp, open_, high, low, close = row[:5]
            volume = row[5] if len(row) > 5 else 0
        else:
            continue
        if stamp is None or open_ is None or high is None or low is None or close is None:
            continue
        bars.append(
            [
                int(float(stamp)),
                round(float(open_), 4),
                round(float(high), 4),
                round(float(low), 4),
                round(float(close), 4),
                int(round(float(volume or 0))),
            ]
        )
    bars.sort(key=lambda bar: bar[0])
    return bars


def _q(name: str) -> str:
    from openview.detect import quote_ident

    return quote_ident(name)


def _pad_for(timeframe: str) -> timedelta:
    from openview.candles import _pad

    return _pad(timeframe)


class Registry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.datasets = {item.id: Dataset(item, settings) for item in settings.datasets}

    def open_all(self) -> None:
        for dataset in self.datasets.values():
            dataset.open()

    def get(self, dataset_id: str) -> Dataset:
        if dataset_id not in self.datasets:
            known = ", ".join(self.datasets) or "(none)"
            raise KeyError(f"Unknown dataset {dataset_id!r}. Known: {known}")
        dataset = self.datasets[dataset_id]
        dataset.open()
        if not dataset.ok:
            raise RuntimeError(dataset.error or "Dataset is unavailable")
        return dataset
