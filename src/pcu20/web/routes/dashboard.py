"""Dashboard route — main overview page."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    """Render the main dashboard page."""
    tcp_server = request.app.state.tcp_server
    machine_registry = request.app.state.machine_registry
    share_manager = request.app.state.share_manager
    templates = request.app.state.templates

    return templates.TemplateResponse(request, "dashboard.html", {
        "active_sessions": tcp_server.active_sessions,
        "connected_count": machine_registry.connected_count,
        "total_machines": machine_registry.total_count,
        "shares": share_manager.list_shares(),
    })
