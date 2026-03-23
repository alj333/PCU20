"""Dashboard route — main overview page."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    """Render the main dashboard page."""
    connector_registry = request.app.state.connector_registry
    machine_registry = request.app.state.machine_registry
    share_manager = request.app.state.share_manager
    config = request.app.state.config
    templates = request.app.state.templates

    return templates.TemplateResponse(request, "dashboard.html", {
        "active_sessions": connector_registry.all_sessions(),
        "connected_count": machine_registry.connected_count,
        "total_machines": machine_registry.total_count,
        "machines": machine_registry.list_all(),
        "shares": share_manager.list_shares(),
        "protocols": connector_registry.protocols,
        "base_port": config.pcu20.base_port,
        "num_ports": config.pcu20.num_ports,
    })
