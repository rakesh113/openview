from pathlib import Path

from openview.config import load_settings, settings_from_file


def test_committed_config_points_at_motherduck():
    settings = settings_from_file(Path("openview.yaml"))
    assert [item.id for item in settings.datasets] == ["equities", "indexes", "options", "file"]
    equities = settings.datasets[0]
    assert equities.connect == "md:market_data"
    assert equities.table == "candles_1m"
    assert equities.price_divisor == 100
    assert equities.symbol_source is not None
    assert equities.symbol_source.table == "instruments"
    assert equities.columns.key == "instrument_id"
    indexes = settings.datasets[1]
    assert indexes.native_intervals == {"1m": "1minute", "1d": "day"}
    assert settings.datasets[2].symbol_source is not None
    assert settings.datasets[2].symbol_source.column == "trading_symbol"
    assert settings.datasets[3].kind == "file"
    assert settings.datasets[3].path == "samples/prices.csv"
    assert settings.token_env == "MOTHERDUCK_TOKEN"
    assert settings.timezone == "Asia/Kolkata"
    assert settings.session_open_minutes == 9 * 60 + 15
    assert settings.session_seconds == (15 * 60 + 30 - (9 * 60 + 15)) * 60


def test_database_env_overrides_yaml(monkeypatch):
    monkeypatch.setenv("OPENVIEW_DATABASE", "data/sample.duckdb")
    settings = load_settings()
    assert len(settings.datasets) == 1
    assert settings.datasets[0].connect == "data/sample.duckdb"
