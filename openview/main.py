"""HTTP API and, when the frontend has been built, the chart UI."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from openview.candles import TIMEFRAMES
from openview.config import Settings, load_settings
from openview.datasource import Registry, public_error
from openview.trades import parse_trade_csv, trade_spec

log = logging.getLogger("openview")
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    resolved = settings or load_settings()
    registry = Registry(resolved)
    registry.open_all()

    app = FastAPI(title="OpenView", version="0.1.0")
    app.add_middleware(GZipMiddleware, minimum_size=800)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.registry = registry

    @app.get("/api/health")
    def health() -> dict:
        datasets = [dataset.meta() for dataset in registry.datasets.values()]
        return {"ok": any(item["ok"] for item in datasets), "datasets": [item["id"] for item in datasets]}

    @app.get("/api/meta")
    def meta() -> dict:
        return {
            "timezone": resolved.timezone,
            "session": {"open": resolved.session_open, "close": resolved.session_close},
            "timeframes": list(TIMEFRAMES),
            "datasets": [dataset.meta() for dataset in registry.datasets.values()],
        }

    @app.get("/api/symbols")
    def symbols(
        dataset: str = Query(...),
        q: str | None = None,
        refresh: bool = False,
    ) -> dict:
        source = _dataset(registry, dataset)
        try:
            payload = source.symbols(q, refresh=refresh)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=public_error(exc)) from exc
        return {"dataset": dataset, **payload}

    @app.get("/api/candles")
    def candles(
        dataset: str = Query(...),
        symbol: str = Query(..., min_length=1, max_length=80),
        timeframe: str = Query("5m"),
        before: int | None = None,
        after: int | None = None,
        around: int | None = None,
        limit: int | None = Query(None, ge=1, le=2000),
    ) -> dict:
        if timeframe not in TIMEFRAMES:
            raise HTTPException(status_code=400, detail=f"Unknown timeframe {timeframe}")
        cursors = [value for value in (before, after, around) if value is not None]
        if len(cursors) > 1:
            raise HTTPException(status_code=400, detail="Pass only one of before, after, or around")
        source = _dataset(registry, dataset)
        try:
            return source.candles(
                symbol.strip(),
                timeframe,
                before=before,
                after=after,
                around=around,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=public_error(exc)) from exc

    @app.get("/api/trades/spec")
    def trades_spec() -> dict:
        return trade_spec()

    @app.post("/api/trades/parse")
    async def trades_parse(
        file: UploadFile = File(...),
        default_symbol: str | None = Form(None),
    ) -> dict:
        raw = await file.read()
        if len(raw) > 5_000_000:
            raise HTTPException(status_code=400, detail="CSV is larger than 5 MB")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="CSV must be UTF-8") from exc
        try:
            return parse_trade_csv(text, default_symbol=default_symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
    else:

        @app.get("/")
        def ui_missing() -> dict:
            return {
                "message": "OpenView API is running. Build the frontend with `npm run build` in frontend/ to serve the chart UI.",
            }

    return app


def _dataset(registry: Registry, dataset_id: str):
    try:
        return registry.get(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
