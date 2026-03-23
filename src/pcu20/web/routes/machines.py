"""Machine management routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def machines_page(request: Request):
    """Render the machines page."""
    machine_registry = request.app.state.machine_registry
    templates = request.app.state.templates

    return templates.TemplateResponse(request, "machines.html", {
        "machines": machine_registry.list_all(),
        "connected": machine_registry.list_connected(),
    })


@router.get("/api/list")
async def api_machines_list(request: Request):
    """API: list all known machines."""
    machine_registry = request.app.state.machine_registry
    return {
        "machines": machine_registry.list_all(),
        "connected_count": machine_registry.connected_count,
    }


@router.get("/api/connected")
async def api_machines_connected(request: Request):
    """API: list currently connected machines."""
    tcp_server = request.app.state.tcp_server
    return {"sessions": tcp_server.active_sessions}
