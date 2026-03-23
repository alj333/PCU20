"""Registry for tracking connected CNC machines."""

from __future__ import annotations

import structlog

from pcu20.machines.models import Machine

log = structlog.get_logger()


class MachineRegistry:
    """Tracks all known CNC machines by machine_id."""

    def __init__(self) -> None:
        self._machines: dict[str, Machine] = {}

    def on_connect(self, ip: str, session_id: str,
                   machine_id: str = "", protocol_type: str = "pcu20") -> Machine:
        """Record a machine connection (typically from inbound PCU20)."""
        mid = machine_id or ip
        if mid not in self._machines:
            self._machines[mid] = Machine(ip=ip, machine_id=mid,
                                          protocol_type=protocol_type)
            log.info("machines.new", machine_id=mid, ip=ip, protocol=protocol_type)

        machine = self._machines[mid]
        machine.touch()
        machine.total_connections += 1
        machine.is_connected = True
        machine.current_session_id = session_id
        return machine

    def on_disconnect(self, machine_id: str, bytes_transferred: int = 0,
                      files_transferred: int = 0) -> None:
        """Record a machine disconnection."""
        machine = self._machines.get(machine_id)
        if machine:
            machine.is_connected = False
            machine.current_session_id = None
            machine.total_bytes_transferred += bytes_transferred
            machine.total_files_transferred += files_transferred

    def register_configured(self, machine_id: str, ip: str, name: str,
                            protocol_type: str, cnc_type: str = "") -> Machine:
        """Register a machine from configuration (FOCAS2 machines)."""
        if machine_id in self._machines:
            return self._machines[machine_id]
        machine = Machine(
            ip=ip, name=name, protocol_type=protocol_type,
            cnc_type=cnc_type, machine_id=machine_id,
        )
        self._machines[machine_id] = machine
        log.info("machines.configured", machine_id=machine_id, ip=ip,
                 protocol=protocol_type, cnc_type=cnc_type)
        return machine

    def update_status(self, machine_id: str, status_data: dict) -> None:
        """Update live status for a machine (called by poller)."""
        machine = self._machines.get(machine_id)
        if machine:
            machine.update_status(status_data)

    def get(self, machine_id: str) -> Machine | None:
        return self._machines.get(machine_id)

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
