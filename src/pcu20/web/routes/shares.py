"""Share management routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def shares_page(request: Request):
    """Render the shares management page."""
    share_manager = request.app.state.share_manager
    templates = request.app.state.templates

    return templates.TemplateResponse(request, "shares.html", {
        "shares": share_manager.list_shares(),
    })


@router.get("/api/list")
async def api_shares_list(request: Request):
    """API: list all configured shares."""
    share_manager = request.app.state.share_manager
    return {"shares": share_manager.list_shares()}
