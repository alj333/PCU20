"""Log viewer routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def logs_page(request: Request):
    """Render the log viewer page."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "logs.html")
