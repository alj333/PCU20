"""File browser routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pcu20.storage.filesystem import list_directory, get_disk_usage

router = APIRouter()


@router.get("/")
async def files_page(request: Request):
    """Render the file browser page."""
    share_manager = request.app.state.share_manager
    templates = request.app.state.templates

    shares = share_manager.list_shares()
    return templates.TemplateResponse(request, "files.html", {
        "shares": shares,
    })


@router.get("/api/browse")
async def api_browse(request: Request, share: str, path: str = ""):
    """API: browse files in a share."""
    share_manager = request.app.state.share_manager
    virtual_path = f"/{share}/{path}" if path else f"/{share}"
    local_path = share_manager.resolve(virtual_path, "")

    if local_path is None or not local_path.is_dir():
        return JSONResponse({"error": "Directory not found", "entries": []}, status_code=404)

    entries = list_directory(local_path)
    usage = get_disk_usage(local_path)

    return {
        "share": share,
        "path": path,
        "entries": entries,
        "disk_usage": usage,
    }


@router.get("/api/history")
async def api_file_history(request: Request, share: str, path: str):
    """API: get version history for a file."""
    share_manager = request.app.state.share_manager
    version_manager = request.app.state.version_manager

    virtual_path = f"/{share}/{path}"
    local_path = share_manager.resolve(virtual_path, "")

    if local_path is None or not local_path.is_file():
        return JSONResponse({"error": "File not found", "history": []}, status_code=404)

    history = version_manager.get_history(local_path)
    return {"file": path, "history": history}
