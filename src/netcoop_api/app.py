"""FastAPI application factory for NetCoop AI backend integration."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from netcoop_api.events import event_sink
from netcoop_api.routes import assistant, health, runs, scenarios, sessions


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Sets the event loop for the execution event sink on startup."""
    loop = asyncio.get_running_loop()
    event_sink.set_loop(loop)
    yield


def create_app() -> FastAPI:
    """Builds and configures the FastAPI NetCoop AI backend service."""
    app = FastAPI(
        title="NetCoop AI API",
        description="Backend API and Event Service for NetCoop AI Diagnostic Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Restrict CORS narrowly to local development environments
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Mount routers
    app.include_router(health.router)
    app.include_router(scenarios.router)
    app.include_router(runs.router)
    app.include_router(sessions.router)
    app.include_router(assistant.router)

    # Mount compiled web frontend if available
    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web_dist.is_dir():
        app.mount("/ui", StaticFiles(directory=str(web_dist), html=True), name="ui")
        if (web_dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=str(web_dist / "assets")), name="assets")

        @app.get("/ui")
        def ui_redirect():
            return RedirectResponse(url="/ui/")

    @app.get("/")
    def root():
        return {
            "name": "NetCoop AI API",
            "status": "online",
            "docs_url": "/docs",
            "dashboard_url": "/ui" if web_dist.is_dir() else None,
        }

    return app
