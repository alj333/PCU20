"""Machine management routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

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
    connector_registry = request.app.state.connector_registry
    return {"sessions": connector_registry.all_sessions()}


@router.get("/api/status/{machine_id}")
async def api_machine_status(request: Request, machine_id: str):
    """API: get live status for a specific machine."""
    machine = request.app.state.machine_registry.get(machine_id)
    if not machine:
        return JSONResponse({"error": "Machine not found"}, status_code=404)
    return machine.summary()
