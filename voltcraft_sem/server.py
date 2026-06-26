"""FastAPI application: REST API + static web UI."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .db import Database
from .device import DeviceManager

log = logging.getLogger(__name__)
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def create_app(settings: Settings) -> FastAPI:
    db = Database(settings.db_path)
    manager = DeviceManager(settings, db)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(manager.run())
        yield
        manager.stop()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="Voltcraft SEM-3600BT", version=__version__, lifespan=lifespan)

    @app.get("/")
    def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    @app.get("/api/status")
    def status():
        st = manager.status()
        cfg = db.get_config()
        w = (st["latest"] or {}).get("w")
        st["currency"] = cfg["currency"]
        st["price_per_kwh"] = cfg["price_per_kwh"]
        st["cost_per_hour"] = (
            round((w or 0.0) / 1000.0 * cfg["price_per_kwh"], 4) if w is not None else None
        )
        return st

    @app.post("/api/switch")
    async def switch(req: Request):
        body = await req.json()
        on = bool(body.get("on"))
        try:
            await manager.switch(on)
            return {"ok": True, "on": on}
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(e)}, status_code=503)

    @app.post("/api/rescan")
    def rescan():
        manager.request_rescan()
        return {"ok": True}

    @app.get("/api/history")
    def history(minutes: int = 60):
        cfg = db.get_config()
        price = cfg["price_per_kwh"]
        e_today = db.energy_today()
        e_range = db.energy_range(minutes)
        return {
            "minutes": minutes,
            "points": db.history(minutes),
            "energy_kwh_today": round(e_today, 4),
            "energy_kwh_range": round(e_range, 4),
            "cost_today": round(e_today * price, 4),
            "cost_range": round(e_range * price, 4),
            "currency": cfg["currency"],
            "price_per_kwh": price,
        }

    @app.get("/api/config")
    def get_config():
        return db.get_config()

    @app.post("/api/config")
    async def set_config(req: Request):
        body = await req.json()
        price = body.get("price_per_kwh")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "invalid price"}, status_code=400)
        return db.set_config(price_per_kwh=price, currency=body.get("currency"))

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
