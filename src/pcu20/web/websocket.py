"""WebSocket hub for real-time dashboard updates."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import structlog

log = structlog.get_logger()

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Stream real-time events to the web dashboard."""
    await ws.accept()
    event_bus = ws.app.state.event_bus

    log.info("websocket.connected")

    try:
        async for event in event_bus.subscribe():
            if ws.client_state == WebSocketState.DISCONNECTED:
                break
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("websocket.error")
    finally:
        log.info("websocket.disconnected")
