"""Command dispatcher and handler registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from pcu20.protocol.discovery import ProtocolDiscovery
from pcu20.protocol.types import CommandId, Frame

log = structlog.get_logger()

# Type alias for command handlers
HandlerFunc = Callable[..., Awaitable[bytes]]


class CommandRegistry:
    """Registry mapping command IDs to handler functions."""

    def __init__(self, discovery: ProtocolDiscovery) -> None:
        self._handlers: dict[int, tuple[str, HandlerFunc]] = {}
        self._discovery = discovery

    def register(self, cmd_id: int, name: str, handler: HandlerFunc) -> None:
        """Register a handler for a command ID."""
        self._handlers[cmd_id] = (name, handler)
        log.debug("commands.registered", cmd=name, cmd_id=f"0x{cmd_id:02X}")

    async def dispatch(self, session: Any, frame: Frame) -> bytes | None:
        """Dispatch a frame to the appropriate handler.

        Returns the response bytes to send, or None if no response.
        """
        session.touch()
        session.commands_processed += 1

        if frame.command_id in self._handlers:
            name, handler = self._handlers[frame.command_id]
            log.info(
                "command.dispatch",
                session=session.id[:8],
                cmd=name,
                payload_len=len(frame.payload),
            )
            try:
                return await handler(session, frame.payload)
            except Exception:
                log.exception(
                    "command.handler_error",
                    session=session.id[:8],
                    cmd=name,
                )
                return None
        else:
            self._discovery.log_unknown_command(
                session.id, frame.command_id, frame.payload
            )
            return None

    @property
    def registered_commands(self) -> list[str]:
        return [name for name, _ in self._handlers.values()]
