"""Per-connection session state machine."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pcu20.protocol.types import FileHandle, SessionState


@dataclass
class Session:
    """Tracks state for a single CNC connection."""

    peer_address: tuple[str, int]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: SessionState = SessionState.CONNECTED
    username: str | None = None
    machine_name: str | None = None

    # Open file handles (handle_id -> FileHandle)
    file_handles: dict[int, FileHandle] = field(default_factory=dict)
    _next_handle_id: int = 1

    # Timestamps
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    authenticated_at: float | None = None

    # Statistics
    bytes_sent: int = 0
    bytes_received: int = 0
    commands_processed: int = 0
    files_transferred: int = 0

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.time()

    def authenticate(self, username: str) -> None:
        """Mark session as authenticated."""
        self.state = SessionState.AUTHENTICATED
        self.username = username
        self.authenticated_at = time.time()

    def disconnect(self) -> None:
        """Mark session as disconnected."""
        self.state = SessionState.DISCONNECTED

    @property
    def is_authenticated(self) -> bool:
        return self.state == SessionState.AUTHENTICATED

    @property
    def peer_ip(self) -> str:
        return self.peer_address[0]

    @property
    def uptime(self) -> float:
        return time.time() - self.connected_at

    def allocate_handle(self, path: str, mode: str) -> int:
        """Allocate a new file handle ID."""
        handle_id = self._next_handle_id
        self._next_handle_id += 1
        self.file_handles[handle_id] = FileHandle(
            handle_id=handle_id, path=path, mode=mode
        )
        return handle_id

    def close_handle(self, handle_id: int) -> FileHandle | None:
        """Close and return a file handle."""
        return self.file_handles.pop(handle_id, None)

    def close_all_handles(self) -> None:
        """Close all open file handles."""
        self.file_handles.clear()

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serializable summary for the web dashboard."""
        return {
            "id": self.id[:8],
            "peer_ip": self.peer_ip,
            "peer_port": self.peer_address[1],
            "state": self.state.value,
            "username": self.username,
            "machine_name": self.machine_name,
            "connected_at": self.connected_at,
            "last_activity": self.last_activity,
            "uptime": round(self.uptime, 1),
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "commands_processed": self.commands_processed,
            "files_transferred": self.files_transferred,
            "open_handles": len(self.file_handles),
        }
