"""Load dataset configuration from openview.yaml and environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"


@dataclass
class ColumnOverride:
    symbol: str | None = None
    time: str | None = None
    open: str | None = None
    high: str | None = None
    low: str | None = None
    close: str | None = None
    volume: str | None = None
    # Fact-table key when the symbol lives on another table (instrument_id).
    key: str | None = None


@dataclass
class SymbolSource:
    """Small dimension table. Symbol lists and key lookups read this, not the fact table."""

    schema: str
    table: str
    key: str
    column: str
    label: str | None = None

    @property
    def qualified_name(self) -> str:
        return f'"{self.schema}"."{self.table}"'


@dataclass
class DatasetConfig:
    id: str
    label: str
    # duckdb reads a database. file reads CSV or Parquet. http proxies another candles API.
    kind: str = "duckdb"
    connect: str = ""
    path: str | None = None
    url: str | None = None
    symbols_url: str | None = None
    symbol_list: list[str] = field(default_factory=list)
    table: str | None = None
    time_stored_as: str | None = None
    columns: ColumnOverride = field(default_factory=ColumnOverride)
    price_divisor: float = 1.0
    interval_column: str | None = None
    native_intervals: dict[str, str] = field(default_factory=dict)
    symbol_source: SymbolSource | None = None


@dataclass
class Settings:
    timezone: str = "Asia/Kolkata"
    session_open: str = "09:15"
    session_close: str = "15:30"
    token_env: str = "MOTHERDUCK_TOKEN"
    datasets: list[DatasetConfig] = field(default_factory=list)

    @property
    def session_open_minutes(self) -> int:
        return _hhmm_to_minutes(self.session_open)

    @property
    def session_close_minutes(self) -> int:
        return _hhmm_to_minutes(self.session_close)

    @property
    def session_seconds(self) -> int:
        span = self.session_close_minutes - self.session_open_minutes
        if span <= 0:
            raise ValueError("session_close must be after session_open")
        return span * 60


def _hhmm_to_minutes(value: str) -> int:
    hour, minute = value.strip().split(":")
    h, m = int(hour), int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid clock time: {value}")
    return h * 60 + m


def _ident(value, label: str) -> str:
    text = str(value)
    if not re.fullmatch(IDENT, text):
        raise ValueError(f"Invalid {label} {value!r}")
    return text


def _optional_ident(value, label: str) -> str | None:
    if value is None or value == "":
        return None
    return _ident(value, label)


def _column_override(raw: dict | None) -> ColumnOverride:
    raw = raw or {}
    return ColumnOverride(
        symbol=_optional_ident(raw.get("symbol"), "column"),
        time=_optional_ident(raw.get("time"), "column"),
        open=_optional_ident(raw.get("open"), "column"),
        high=_optional_ident(raw.get("high"), "column"),
        low=_optional_ident(raw.get("low"), "column"),
        close=_optional_ident(raw.get("close"), "column"),
        volume=_optional_ident(raw.get("volume"), "column"),
        key=_optional_ident(raw.get("key"), "column"),
    )


def _http_url(value: str, label: str) -> str:
    text = str(value).strip()
    if not (text.startswith("https://") or text.startswith("http://")):
        raise ValueError(f"{label} must be an http(s) URL")
    return text


def _symbol_source(raw: dict | None) -> SymbolSource | None:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("symbols must name a table, key, and column")
    return SymbolSource(
        schema=_ident(raw.get("schema") or "main", "schema"),
        table=_ident(raw["table"], "symbols table"),
        key=_ident(raw["key"], "symbols key"),
        column=_ident(raw["column"], "symbols column"),
        label=_optional_ident(raw.get("label"), "symbols label"),
    )


def _native_intervals(raw: dict | None) -> dict[str, str]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("native_intervals must be a mapping of timeframe to interval value")
    allowed = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}
    mapped: dict[str, str] = {}
    for timeframe, value in raw.items():
        name = str(timeframe)
        if name not in allowed:
            raise ValueError(f"Unknown timeframe in native_intervals: {name}")
        text = str(value)
        if not re.fullmatch(r"[A-Za-z0-9_]+", text):
            raise ValueError(f"Invalid interval value {value!r}")
        mapped[name] = text
    return mapped


def _dataset(raw: dict) -> DatasetConfig:
    kind = str(raw.get("kind") or "duckdb")
    if kind not in {"duckdb", "file", "http"}:
        raise ValueError(f"kind must be duckdb, file, or http (got {kind})")
    stored = raw.get("time_stored_as")
    if stored is not None and stored not in {"timestamptz", "exchange", "utc"}:
        raise ValueError(f"time_stored_as must be timestamptz, exchange, or utc (got {stored})")
    divisor = float(raw.get("price_divisor") or 1)
    if divisor <= 0 or divisor != divisor:
        raise ValueError("price_divisor must be a positive number")
    url = _http_url(raw["url"], "url") if kind == "http" else None
    symbols_url = _http_url(raw["symbols_url"], "symbols_url") if raw.get("symbols_url") else None
    path = str(raw["path"]) if raw.get("path") else None
    connect = str(raw.get("connect") or "")
    if kind == "duckdb" and not connect:
        raise ValueError(f"Dataset {raw.get('id')} needs connect")
    if kind == "file" and not (path or connect):
        raise ValueError(f"Dataset {raw.get('id')} needs path")
    if kind == "http":
        connect = url or ""
    elif kind == "file" and path:
        connect = path
    symbol_list = [str(item) for item in (raw.get("symbol_list") or [])]
    return DatasetConfig(
        id=str(raw["id"]),
        label=str(raw.get("label") or raw["id"]),
        kind=kind,
        connect=connect,
        path=path,
        url=url,
        symbols_url=symbols_url,
        symbol_list=symbol_list,
        table=raw.get("table"),
        time_stored_as=stored,
        columns=_column_override(raw.get("columns")),
        price_divisor=divisor,
        interval_column=_optional_ident(raw.get("interval_column"), "interval_column"),
        native_intervals=_native_intervals(raw.get("native_intervals")),
        symbol_source=_symbol_source(raw.get("symbols")),
    )


def settings_from_mapping(raw: dict) -> Settings:
    datasets = [_dataset(item) for item in raw.get("datasets") or []]
    if not datasets:
        raise ValueError("Configure at least one dataset")
    ids = [item.id for item in datasets]
    if len(ids) != len(set(ids)):
        raise ValueError("Dataset ids must be unique")
    settings = Settings(
        timezone=str(raw.get("timezone") or "Asia/Kolkata"),
        session_open=str(raw.get("session_open") or "09:15"),
        session_close=str(raw.get("session_close") or "15:30"),
        token_env=str(raw.get("token_env") or "MOTHERDUCK_TOKEN"),
        datasets=datasets,
    )
    # Validate session bounds early.
    settings.session_seconds
    return settings


def default_config_path() -> Path | None:
    env = os.environ.get("OPENVIEW_CONFIG")
    if env:
        return Path(env)
    for candidate in (Path.cwd() / "openview.yaml", REPO_ROOT / "openview.yaml"):
        if candidate.exists():
            return candidate
    return None


def settings_from_file(path: Path) -> Settings:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping")
    return settings_from_mapping(raw)


def load_settings() -> Settings:
    """YAML defaults, then OPENVIEW_DATABASE replaces the dataset list when set."""
    path = default_config_path()
    if path is not None:
        settings = settings_from_file(path)
    else:
        settings = settings_from_mapping(
            {
                "datasets": [
                    {"id": "equities", "label": "NSE Equities", "connect": "md:market_data"},
                    {"id": "options", "label": "NSE Options", "connect": "md:options_data"},
                ]
            }
        )
    override = os.environ.get("OPENVIEW_DATABASE")
    if override:
        label = "MotherDuck" if override.startswith("md:") else "Local DuckDB"
        settings.datasets = [
            DatasetConfig(id="equities", label=label, connect=override),
        ]
    token_env = os.environ.get("OPENVIEW_TOKEN_ENV")
    if token_env:
        settings.token_env = token_env
    return settings


def resolve_connect(connect: str) -> str:
    """Resolve a local database path. MotherDuck URIs are returned unchanged."""
    if connect.startswith("md:"):
        return connect
    path = Path(connect)
    if path.is_absolute():
        return str(path)
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return str(cwd_path)
    root_path = REPO_ROOT / path
    if root_path.exists():
        return str(root_path)
    return str(cwd_path)
