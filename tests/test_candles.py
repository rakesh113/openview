from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb
from fastapi.testclient import TestClient

from openview.config import ColumnOverride, DatasetConfig, Settings, SymbolSource
from openview.datasource import Registry
from openview.main import create_app

IST = ZoneInfo("Asia/Kolkata")


def _settings(path) -> Settings:
    return Settings(
        datasets=[DatasetConfig(id="equities", label="Equities", connect=str(path))],
    )


def _load(path, *, naive: bool = False) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE notes (id INTEGER, body VARCHAR)")
    con.execute("INSERT INTO notes VALUES (1, 'ignore me')")
    tz = "TIMESTAMP" if naive else "TIMESTAMPTZ"
    con.execute(
        f"""
        CREATE TABLE candles (
            symbol VARCHAR,
            ts {tz},
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT
        )
        """
    )
    rows = [
        ("RELIANCE", "2024-01-03 09:14:00", 1, 1, 1, 1, 1),  # before the session
        ("RELIANCE", "2024-01-03 09:15:00", 100, 101, 99, 100.5, 10),
        ("RELIANCE", "2024-01-03 09:16:00", 100.5, 102, 100, 101, 12),
        ("RELIANCE", "2024-01-03 09:19:00", 101, 103, 100.5, 102, 8),
        ("RELIANCE", "2024-01-03 09:20:00", 102, 104, 101, 103, 20),
        ("RELIANCE", "2024-01-03 10:14:00", 110, 111, 109, 110.5, 5),
        ("RELIANCE", "2024-01-03 10:15:00", 110.5, 112, 110, 111, 7),
        ("RELIANCE", "2024-01-03 15:29:00", 120, 121, 119, 120.5, 3),
        ("RELIANCE", "2024-01-03 15:30:00", 999, 999, 999, 999, 9),  # session is over
        ("RELIANCE", "2024-01-04 09:15:00", 130, 132, 129, 131, 15),
        ("TCS", "2024-01-03 09:15:00", 50, 51, 49, 50, 4),
    ]
    if naive:
        con.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    else:
        stamped = [
            (symbol, datetime.fromisoformat(f"{ts}+05:30"), o, h, l, c, v)
            for symbol, ts, o, h, l, c, v in rows
        ]
        con.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)", stamped)
    con.close()


def _epoch(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=IST).timestamp())


def test_intraday_buckets_are_session_aligned(tmp_path):
    path = tmp_path / "market.duckdb"
    _load(path)
    registry = Registry(_settings(path))
    page = registry.get("equities").candles("RELIANCE", "5m")
    by_time = {bar[0]: bar for bar in page["bars"]}

    first = by_time[_epoch("2024-01-03 09:15:00")]
    assert first[1:] == [100.0, 103.0, 99.0, 102.0, 30]
    second = by_time[_epoch("2024-01-03 09:20:00")]
    assert second[1] == 102.0 and second[4] == 103.0
    assert _epoch("2024-01-03 10:14:00") not in by_time
    assert by_time[_epoch("2024-01-03 10:10:00")][4] == 110.5
    assert by_time[_epoch("2024-01-03 15:25:00")][4] == 120.5
    assert _epoch("2024-01-03 09:14:00") not in by_time
    assert _epoch("2024-01-03 15:30:00") not in by_time
    assert all(bar[4] != 50 for bar in page["bars"])
    assert page["found"] is True


def test_hourly_daily_and_weekly(tmp_path):
    path = tmp_path / "market.duckdb"
    _load(path)
    source = Registry(_settings(path)).get("equities")
    hourly = {bar[0]: bar for bar in source.candles("RELIANCE", "1h")["bars"]}
    assert hourly[_epoch("2024-01-03 09:15:00")][5] == 10 + 12 + 8 + 20 + 5
    assert _epoch("2024-01-03 10:15:00") in hourly
    assert _epoch("2024-01-03 15:15:00") in hourly

    daily = source.candles("RELIANCE", "1d")["bars"]
    assert len(daily) == 2
    assert daily[0][1] == 100.0
    assert daily[0][4] == 120.5
    assert daily[1][1] == 130.0 and daily[1][4] == 131.0

    weekly = source.candles("RELIANCE", "1w")["bars"]
    assert len(weekly) == 1
    assert weekly[0][1] == 100.0
    assert weekly[0][4] == 131.0


def test_naive_exchange_timestamps(tmp_path):
    path = tmp_path / "naive.duckdb"
    _load(path, naive=True)
    page = Registry(_settings(path)).get("equities").candles("RELIANCE", "5m")
    assert page["bars"][0][0] == _epoch("2024-01-03 09:15:00")
    meta = Registry(_settings(path)).datasets["equities"].meta()
    assert meta["columns"]["time_stored_as"] == "exchange"
    assert meta["table"] == "main.candles"


def test_history_pages_do_not_repeat_the_boundary_bar(tmp_path):
    path = tmp_path / "market.duckdb"
    _load(path)
    source = Registry(_settings(path)).get("equities")
    latest = source.candles("RELIANCE", "1d")
    assert latest["has_more"] is False
    older = source.candles("RELIANCE", "5m", before=latest["bars"][0][0])
    latest_times = {bar[0] for bar in source.candles("RELIANCE", "5m")["bars"]}
    older_times = {bar[0] for bar in older["bars"]}
    # The latest page already contains every January bar; paging before the
    # daily epoch (midnight IST) must not duplicate 5-minute buckets.
    assert older_times.isdisjoint(latest_times) or older["bars"] == []


def test_missing_symbol_is_empty(tmp_path):
    path = tmp_path / "market.duckdb"
    _load(path)
    page = Registry(_settings(path)).get("equities").candles("INFY", "1m")
    assert page["found"] is False
    assert page["bars"] == []


def test_api_serves_symbols_and_candles(tmp_path):
    path = tmp_path / "market.duckdb"
    _load(path)
    client = TestClient(create_app(_settings(path)))
    meta = client.get("/api/meta").json()
    assert meta["datasets"][0]["ok"] is True
    assert meta["timeframes"][0] == "1m"
    symbols = client.get("/api/symbols", params={"dataset": "equities"}).json()
    assert symbols["symbols"] == ["RELIANCE", "TCS"]
    searched = client.get("/api/symbols", params={"dataset": "equities", "q": "tc"}).json()
    assert searched["symbols"] == ["TCS"]
    candles = client.get(
        "/api/candles",
        params={"dataset": "equities", "symbol": "RELIANCE", "timeframe": "15m"},
    ).json()
    assert candles["bars"][0][0] == _epoch("2024-01-03 09:15:00")
    missing = client.get("/api/candles", params={"dataset": "nope", "symbol": "TCS"})
    assert missing.status_code == 404


def test_column_override(tmp_path):
    path = tmp_path / "custom.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE bars (
            tradingsymbol VARCHAR,
            datetime TIMESTAMP,
            open_price DOUBLE,
            high_price DOUBLE,
            low_price DOUBLE,
            close_price DOUBLE,
            vol BIGINT
        )
        """
    )
    con.execute(
        """
        INSERT INTO bars VALUES
        ('INFY', TIMESTAMP '2024-01-03 09:15:00', 10, 11, 9, 10.5, 100),
        ('INFY', TIMESTAMP '2024-01-03 09:16:00', 10.5, 12, 10, 11, 80)
        """
    )
    con.close()
    settings = Settings(
        datasets=[
            DatasetConfig(
                id="equities",
                label="Custom",
                connect=str(path),
                table="bars",
                columns=ColumnOverride(
                    symbol="tradingsymbol",
                    time="datetime",
                    open="open_price",
                    high="high_price",
                    low="low_price",
                    close="close_price",
                    volume="vol",
                ),
            )
        ]
    )
    page = Registry(settings).get("equities").candles("INFY", "1m")
    assert [bar[1] for bar in page["bars"]] == [10.0, 10.5]
    assert page["bars"][0][5] == 100


def test_limit_returns_only_the_latest_slice(tmp_path):
    path = tmp_path / "market.duckdb"
    _load(path)
    source = Registry(_settings(path)).get("equities")
    page = source.candles("RELIANCE", "1m", limit=2)
    assert [bar[0] for bar in page["bars"]] == [
        _epoch("2024-01-03 15:29:00"),
        _epoch("2024-01-04 09:15:00"),
    ]
    assert page["has_more"] is True
    older = source.candles("RELIANCE", "1m", before=page["next_before"], limit=2)
    assert older["bars"]
    assert older["bars"][-1][0] < page["bars"][0][0]
    assert {bar[0] for bar in older["bars"]}.isdisjoint({bar[0] for bar in page["bars"]})


def test_paise_fact_table_uses_the_instrument_key(tmp_path):
    path = tmp_path / "paise.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE instruments (instrument_id INTEGER, symbol VARCHAR, name VARCHAR)")
    con.execute("INSERT INTO instruments VALUES (395, 'RELIANCE', 'Reliance Industries Ltd.'), (441, 'TCS', 'Tata Consultancy')")
    con.execute(
        """
        CREATE TABLE candles_1m (
            ts TIMESTAMPTZ,
            instrument_id INTEGER,
            open INTEGER,
            high INTEGER,
            low INTEGER,
            close INTEGER,
            volume INTEGER
        )
        """
    )
    rows = [
        (395, "2024-01-03 09:15:00", 10000, 10100, 9900, 10050, 10),
        (395, "2024-01-03 09:16:00", 10050, 10300, 10000, 10200, 12),
        (441, "2024-01-03 09:15:00", 5000, 5100, 4900, 5000, 4),
    ]
    con.executemany(
        "INSERT INTO candles_1m VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(datetime.fromisoformat(f"{ts}+05:30"), key, o, h, l, c, v) for key, ts, o, h, l, c, v in rows],
    )
    con.close()
    settings = Settings(
        datasets=[
            DatasetConfig(
                id="equities",
                label="Equities",
                connect=str(path),
                table="candles_1m",
                price_divisor=100,
                symbol_source=SymbolSource(schema="main", table="instruments", key="instrument_id", column="symbol", label="name"),
                columns=ColumnOverride(key="instrument_id", time="ts", open="open", high="high", low="low", close="close", volume="volume"),
            )
        ]
    )
    source = Registry(settings).get("equities")
    listed = source.symbols()
    assert listed["symbols"] == ["RELIANCE", "TCS"]
    assert listed["labels"]["RELIANCE"] == "Reliance Industries Ltd."
    page = source.candles("RELIANCE", "5m")
    assert page["bars"][0][1:] == [100.0, 103.0, 99.0, 102.0, 22]
    assert source.candles("MISSING", "5m")["found"] is False


def test_native_daily_bars_skip_the_session_filter(tmp_path):
    path = tmp_path / "index.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE index_candles (
            symbol VARCHAR,
            ts TIMESTAMPTZ,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            interval VARCHAR
        )
        """
    )
    minute = datetime.fromisoformat("2024-01-03 09:15:00+05:30")
    later = datetime.fromisoformat("2024-01-03 09:16:00+05:30")
    daily = datetime.fromisoformat("2024-01-03 18:30:00+00:00")
    con.executemany(
        "INSERT INTO index_candles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("NIFTY50", minute, 100, 103, 99, 102, 10, "1minute"),
            ("NIFTY50", later, 102, 104, 101, 103, 8, "1minute"),
            ("NIFTY50", minute, 999, 999, 999, 999, 1, "day"),
            ("NIFTY50", daily, 22000, 22100, 21900, 22050, 0, "day"),
        ],
    )
    con.close()
    settings = Settings(
        datasets=[
            DatasetConfig(
                id="indexes",
                label="Indexes",
                connect=str(path),
                table="index_candles",
                interval_column="interval",
                native_intervals={"1m": "1minute", "1d": "day"},
                columns=ColumnOverride(symbol="symbol", time="ts", open="open", high="high", low="low", close="close", volume="volume"),
            )
        ]
    )
    source = Registry(settings).get("indexes")
    intraday = source.candles("NIFTY50", "5m")
    assert intraday["bars"][0][2] == 104.0
    daily_page = {bar[0]: bar for bar in source.candles("NIFTY50", "1d")["bars"]}
    assert int(daily.timestamp()) in daily_page
    assert daily_page[int(daily.timestamp())][1] == 22000.0


def test_csv_file_returns_a_time_window(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text(
        "symbol,ts,open,high,low,close,volume\n"
        "RELIANCE,2024-06-18 09:15:00,10,11,9,10.5,100\n"
        "RELIANCE,2024-06-18 09:16:00,10.5,12,10,11,80\n"
        "RELIANCE,2024-06-18 09:17:00,11,12,10.5,11.5,70\n"
        "TCS,2024-06-18 09:15:00,20,21,19,20,5\n",
        encoding="utf-8",
    )
    settings = Settings(datasets=[DatasetConfig(id="file", label="File", kind="file", connect=str(path), path=str(path))])
    source = Registry(settings).get("file")
    page = source.candles("RELIANCE", "1m", limit=2)
    assert len(page["bars"]) == 2
    assert page["bars"][-1][1] == 11.0
    assert page["has_more"] is True
    older = source.candles("RELIANCE", "1m", before=page["next_before"], limit=2)
    assert [bar[1] for bar in older["bars"]] == [10.0]
    assert source.symbols()["symbols"] == ["RELIANCE", "TCS"]


def test_http_source_fetches_a_window(tmp_path):
    del tmp_path
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import parse_qs, urlparse

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/symbols":
                body = {"symbols": ["AAA", "BBB"]}
            else:
                limit = int(query.get("limit", ["10"])[0])
                before = int(query["before"][0]) if "before" in query else 1_700_000_000 + limit * 60
                bars = []
                for step in range(limit):
                    stamp = before - (limit - step) * 60
                    bars.append([stamp, 10 + step, 11 + step, 9, 10.5 + step, 3])
                body = {"bars": bars}
            raw = __import__("json").dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        settings = Settings(
            datasets=[
                DatasetConfig(
                    id="remote",
                    label="Remote",
                    kind="http",
                    connect=f"http://127.0.0.1:{port}/candles",
                    url=f"http://127.0.0.1:{port}/candles",
                    symbols_url=f"http://127.0.0.1:{port}/symbols",
                )
            ]
        )
        source = Registry(settings).get("remote")
        assert source.symbols()["symbols"] == ["AAA", "BBB"]
        page = source.candles("AAA", "1m", limit=3)
        assert len(page["bars"]) == 3
        assert page["has_more"] is True
        older = source.candles("AAA", "1m", before=page["next_before"], limit=3)
        assert older["bars"][-1][0] < page["bars"][0][0]
    finally:
        server.shutdown()
