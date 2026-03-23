"""Registry for tracking connected CNC machines."""

from __future__ import annotations

import structlog

from pcu20.machines.models import Machine

log = structlog.get_logger()


class MachineRegistry:
    """Tracks all known CNC machines by IP address."""

    def __init__(self) -> None:
        self._machines: dict[str, Machine] = {}

    def on_connect(self, ip: str, session_id: str) -> Machine:
        """Record a machine connection."""
        if ip not in self._machines:
            self._machines[ip] = Machine(ip=ip)
            log.info("machines.new", ip=ip)

        machine = self._machines[ip]
        machine.touch()
        machine.total_connections += 1
        machine.is_connected = True
        machine.current_session_id = session_id
        return machine

    def on_disconnect(self, ip: str, bytes_transferred: int = 0,
                      files_transferred: int = 0) -> None:
        """Record a machine disconnection."""
        machine = self._machines.get(ip)
        if machine:
            machine.is_connected = False
            machine.current_session_id = None
            machine.total_bytes_transferred += bytes_transferred
            machine.total_files_transferred += files_transferred

    def get(self, ip: str) -> Machine | None:
        return self._machines.get(ip)

    def list_all(self) -> list[dict]:
        return [m.summary() for m in self._machines.values()]

    def list_connected(self) -> list[dict]:
        return [m.summary() for m in self._machines.values() if m.is_connected]

    @property
    def connected_count(self) -> int:
        return sum(1 for m in self._machines.values() if m.is_connected)

    @property
    def total_count(self) -> int:
        return len(self._machines)
