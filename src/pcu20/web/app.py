"""FastAPI web application factory."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    from pcu20.config import AppConfig
    from pcu20.event_bus import EventBus
    from pcu20.machines.registry import MachineRegistry
    from pcu20.protocol.registry import ConnectorRegistry
    from pcu20.storage.shares import ShareManager
    from pcu20.storage.versioning import VersionManager

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def create_web_app(
    connector_registry: ConnectorRegistry,
    event_bus: EventBus,
    share_manager: ShareManager,
    version_manager: VersionManager,
    machine_registry: MachineRegistry,
    config: AppConfig,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CNC Network Manager",
        description="Web dashboard for multi-protocol CNC file server",
        version="0.2.0",
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Store shared state for routes
    app.state.connector_registry = connector_registry
    app.state.event_bus = event_bus
    app.state.share_manager = share_manager
    app.state.version_manager = version_manager
    app.state.machine_registry = machine_registry
    app.state.config = config
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Register routes
    from pcu20.web.routes.dashboard import router as dashboard_router
    from pcu20.web.routes.machines import router as machines_router
    from pcu20.web.routes.shares import router as shares_router
    from pcu20.web.routes.files import router as files_router
    from pcu20.web.routes.logs import router as logs_router
    from pcu20.web.routes.probe import router as probe_router
    from pcu20.web.routes.setup import router as setup_router
    from pcu20.web.websocket import router as ws_router

    app.include_router(dashboard_router)
    app.include_router(machines_router, prefix="/machines")
    app.include_router(shares_router, prefix="/shares")
    app.include_router(files_router, prefix="/files")
    app.include_router(logs_router, prefix="/logs")
    app.include_router(probe_router, prefix="/probe")
    app.include_router(setup_router, prefix="/setup")
    app.include_router(ws_router)

    return app
