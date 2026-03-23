"""Machine data models for tracking connected CNC controllers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Machine:
    """Represents a known CNC machine."""

    ip: str
    name: str = ""
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    total_connections: int = 0
    total_files_transferred: int = 0
    total_bytes_transferred: int = 0
    is_connected: bool = False
    current_session_id: str | None = None

    def touch(self) -> None:
        self.last_seen = time.time()

    def summary(self) -> dict:
        return {
            "ip": self.ip,
            "name": self.name or self.ip,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "total_connections": self.total_connections,
            "total_files_transferred": self.total_files_transferred,
            "is_connected": self.is_connected,
        }
