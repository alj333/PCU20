"""Machine data models for tracking connected CNC controllers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Machine:
    """Represents a known CNC machine (any protocol)."""

    ip: str
    name: str = ""
    protocol_type: str = "pcu20"       # "pcu20" | "focas2"
    cnc_type: str = ""                 # "sinumerik-810d", "fanuc-30i", "mori-mapps", etc.
    machine_id: str = ""               # Config-defined ID or IP for PCU20

    # Connection tracking
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    total_connections: int = 0
    total_files_transferred: int = 0
    total_bytes_transferred: int = 0
    is_connected: bool = False
    current_session_id: str | None = None

    # Live CNC status (primarily for FOCAS2 machines)
    cnc_status: str = "unknown"        # running/idle/alarm/stopped
    cnc_mode: str = ""                 # auto/mdi/jog/edit/ref
    current_program: int | None = None
    axis_position: dict[str, float] = field(default_factory=dict)
    active_alarms: list[dict] = field(default_factory=list)
    spindle_speed: float | None = None
    feed_rate: float | None = None
    last_status_update: float | None = None

    def touch(self) -> None:
        self.last_seen = time.time()

    def update_status(self, status_data: dict) -> None:
        """Update live CNC status from a poller event."""
        if "status" in status_data:
            status = status_data["status"]
            self.cnc_status = status.get("run", self.cnc_status)
            self.cnc_mode = status.get("mode", self.cnc_mode)
        self.current_program = status_data.get("program", self.current_program)
        self.axis_position = status_data.get("position", self.axis_position)
        self.active_alarms = status_data.get("alarms", self.active_alarms)
        self.spindle_speed = status_data.get("spindle_speed", self.spindle_speed)
        self.feed_rate = status_data.get("feed_rate", self.feed_rate)
        self.last_status_update = time.time()
        self.touch()

    def summary(self) -> dict:
        base = {
            "ip": self.ip,
            "name": self.name or self.machine_id or self.ip,
            "protocol_type": self.protocol_type,
            "cnc_type": self.cnc_type,
            "machine_id": self.machine_id or self.ip,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "total_connections": self.total_connections,
            "total_files_transferred": self.total_files_transferred,
            "is_connected": self.is_connected,
            "cnc_status": self.cnc_status,
        }
        if self.protocol_type == "focas2":
            base.update({
                "cnc_mode": self.cnc_mode,
                "current_program": self.current_program,
                "axis_position": self.axis_position,
                "active_alarms": self.active_alarms,
                "spindle_speed": self.spindle_speed,
                "feed_rate": self.feed_rate,
            })
        return base
