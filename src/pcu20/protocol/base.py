"""Abstract base classes for CNC protocol connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class ProtocolType(str, Enum):
    PCU20 = "pcu20"
    FOCAS2 = "focas2"


class ConnectionDirection(str, Enum):
    INBOUND = "inbound"    # CNC connects to us (PCU20)
    OUTBOUND = "outbound"  # We connect to CNC (FOCAS2)


class CNCStatus(str, Enum):
    UNKNOWN = "unknown"
    RUNNING = "running"
    IDLE = "idle"
    ALARM = "alarm"
    STOPPED = "stopped"


class BaseProtocolConnector(ABC):
    """Base class for all CNC protocol connectors.

    Subclasses implement either inbound (CNC connects to us) or outbound
    (we connect to CNC) connection patterns, but expose a uniform interface.
    """

    protocol_type: ProtocolType
    direction: ConnectionDirection

    @abstractmethod
    async def start(self) -> None:
        """Start the connector (listen for connections or connect to CNCs)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the connector and clean up all connections."""
        ...

    @abstractmethod
    def get_sessions(self) -> list[dict[str, Any]]:
        """Return a list of active session summaries."""
        ...

    @abstractmethod
    async def list_files(self, machine_id: str, path: str = "") -> list[dict]:
        """List files/programs on a machine or in a share."""
        ...

    @abstractmethod
    async def read_file(self, machine_id: str, path: str) -> bytes | None:
        """Read a file/program from a machine or share."""
        ...

    @abstractmethod
    async def write_file(self, machine_id: str, path: str, data: bytes) -> bool:
        """Write a file/program to a machine or share."""
        ...
