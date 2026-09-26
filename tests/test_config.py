from pathlib import Path

import duckdb

from openview.config import duckdb_target, load_settings, settings_from_file, settings_from_mapping
from openview.datasource import Dataset


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


def test_local_file_is_used_when_it_exists(tmp_path):
    database = tmp_path / "market.duckdb"
    database.write_bytes(b"")
    target, cloud = duckdb_target("md:market_data", str(database))
    assert target == str(database)
    assert cloud is False


def test_missing_local_file_keeps_cloud_connect(tmp_path):
    missing = tmp_path / "missing.duckdb"
    target, cloud = duckdb_target("md:market_data", str(missing))
    assert target == "md:market_data"
    assert cloud is True


def test_filesystem_connect_needs_no_token(tmp_path):
    database = tmp_path / "market.duckdb"
    target, cloud = duckdb_target(str(database), None)
    assert target == str(database)
    assert cloud is False


def test_yaml_local_path_overrides_cloud_when_present(tmp_path):
    database = tmp_path / "market.duckdb"
    _seed(database)
    settings = settings_from_mapping(
        {
            "local": str(database),
            "datasets": [
                {"id": "equities", "connect": "md:market_data", "table": "candles"},
                {
                    "id": "options",
                    "connect": "md:options_data",
                    "path": str(tmp_path / "missing.duckdb"),
                },
            ],
        }
    )
    assert settings.datasets[0].local == str(database)
    assert settings.datasets[1].local == str(tmp_path / "missing.duckdb")
    present = Dataset(settings.datasets[0], settings)
    absent = Dataset(settings.datasets[1], settings)
    assert present.cloud is False
    assert present.connect_target == str(database)
    assert absent.cloud is True
    assert absent.connect_target == "md:options_data"
    present.open()
    assert present.ok
    assert present.error is None


def _seed(path: Path) -> None:
    con = duckdb.connect(str(path))
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
    con.execute(
        """
        INSERT INTO candles VALUES
        ('RELIANCE', '2024-01-03 09:15:00+05:30', 100, 101, 99, 100.5, 10)
        """
    )
    con.close()
