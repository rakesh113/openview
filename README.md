# OpenView

A TradingView-style chart. The browser asks for the candles that fit on screen. Scrolling left or right asks for the next time window. Nothing ships the whole history to the page.

DuckDB, including MotherDuck, is the table structure and the query engine for one of those windows. The same chart can read a CSV or Parquet file, or proxy another candles API. Indicators, drawings, and backtest trades are drawn on the bars already loaded.

## Run it

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python -m uvicorn openview.main:create_app --factory --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000`. For frontend development, run the API on port 8000 and `npm run dev` in `frontend/` (Vite proxies `/api`).

MotherDuck uses the `MOTHERDUCK_TOKEN` environment variable:

```python
duckdb.connect("md:market_data", config={"motherduck_token": token})
```

`openview.yaml` lists the sources. Equities read `md:market_data` `candles_1m` through `instruments.instrument_id`, and prices in paise are divided by 100. Indexes and options read `md:options_data` and filter the `interval` column. `samples/prices.csv` is a file source you can chart without a token. On startup a DuckDB source still detects an OHLC table when `table` is left unset.

```yaml
datasets:
  - id: equities
    kind: duckdb
    connect: md:market_data
    table: candles_1m
    price_divisor: 100
    symbols:
      table: instruments
      key: instrument_id
      column: symbol
      label: name
    columns:
      key: instrument_id
      time: ts
      open: open
      high: high
      low: low
      close: close
      volume: volume
  - id: file
    kind: file
    path: samples/prices.csv
  - id: remote
    kind: http
    url: https://example.invalid/candles
    symbols_url: https://example.invalid/symbols
```

An HTTP source receives `symbol`, `timeframe`, `limit`, and one of `before`, `after`, or `around`. It returns `{"bars": [[time, open, high, low, close, volume]]}` with `time` as a unix second.

`timestamptz` values are converted to Asia/Kolkata. Naive timestamps are treated as exchange-local IST. A local DuckDB file uses the same shape:

```bash
OPENVIEW_DATABASE=data/market.duckdb python -m uvicorn openview.main:create_app --factory
```

`OPENVIEW_DATABASE` replaces the dataset list for that process. `OPENVIEW_CONFIG` points at a different yaml file.

### Sample file

```bash
python -m openview.sample_data data/sample.duckdb
OPENVIEW_DATABASE=data/sample.duckdb python -m uvicorn openview.main:create_app --factory
```

That writes a seeded random walk (not market data) plus `samples/trades.csv`, whose fills sit on those candles.

## Chart

- Candles, volume, and crosshair. The time axis is Asia/Kolkata.
- Timeframes: 1m, 3m, 5m, 15m, 30m, 1H, 4H, 1D, 1W. Intraday buckets start at 09:15 and the session ends at 15:30, so a 5-minute bar is 09:15–09:20 rather than a clock-aligned 09:10.
- Scroll and fling horizontally. The first request is about two screens of bars. Near the left edge the next older window is fetched and prepended without jumping the view. Near the right edge, newer bars load the same way. A **Latest** button returns to the last bar.
- The chart fills the window (`ResizeObserver`). Drag a pane separator to resize price, volume, and oscillators. Drag the price axis to scale manually; **Auto** or a double-click restores it. Drag the time axis to zoom. The watchlist and trade blotter splitters move the same way.
- Indicators: SMA, EMA, Bollinger Bands, session VWAP, RSI, MACD, ATR, volume. They are computed on the bars already loaded, so toggling one does not rescan the database.
- Horizontal price levels and text notes, stored in the browser per symbol.
- Watchlist search. `/` focuses it.

If a database has more symbols than the watchlist can show (options chains), type to search on the server.

## Trade CSV

One row is one round trip. This is the file to produce from a backtest:

| column | required | meaning |
| --- | --- | --- |
| `symbol` | yes, unless you assign the chart symbol | NSE symbol, matched to the candle symbol |
| `side` | yes | `long` or `short` (`buy`/`sell` accepted) |
| `entry_time` | yes | ISO-8601. Naive values are Asia/Kolkata |
| `entry_price` | yes | fill price |
| `exit_time` | no | omit for an open trade |
| `exit_price` | no | |
| `quantity` | no | shares or lots |
| `pnl` | no | realized P&L. If omitted, it is inferred from prices and quantity |
| `tag` | no | strategy name or note |

```csv
symbol,side,entry_time,entry_price,exit_time,exit_price,quantity,pnl,tag
RELIANCE,long,2024-01-15T09:45:00+05:30,2488.50,2024-01-15T11:15:00+05:30,2506.20,100,1770.00,orb
RELIANCE,short,2024-01-16T10:05:00+05:30,2510.00,2024-01-16T13:20:00+05:30,2494.75,50,762.50,vwap
```

Headers already used by the backtest logs are accepted without renaming: `Symbol`, `Type`, `Entry Time`, `Exit Time`, `Entry Price`, `Exit Price`, `PnL`, `Reason`, `Qty`. Entries are arrows, exits are dots, and a line connects the fill prices, green when the trade made money. Click a blotter row to scroll the chart there; if that date is not loaded yet, the API fetches a window around it.

## Keeping scans small

The chart measures its width and sends `limit` (about two screens of bars, capped at 2,000). The server turns that into a short time range and binds it:

```sql
SELECT ...
FROM candles_1m
WHERE instrument_id = ? AND ts >= ? AND ts < ?
GROUP BY session_bucket
ORDER BY t DESC
LIMIT ?
```

Equity prices are divided by 100 in that query. The symbol list comes from `instruments` (500 rows), not from a distinct scan of the minute table. Options search `option_contracts` instead of `option_candles`. Index and option tables store both `1minute` and `day` rows, so every query also filters `interval`.

Cluster or sort the physical table by `(instrument_id, ts)` so MotherDuck can skip other symbols. Do not `SELECT *` the minute table into a dataframe and resample locally.

The browser keeps at most 4,000 bars. Use a higher timeframe for a longer lookback.
