"""Connector registry — manages all protocol connectors."""

from __future__ import annotations

from typing import Any

import structlog

from pcu20.protocol.base import BaseProtocolConnector, ProtocolType

log = structlog.get_logger()


class ConnectorRegistry:
    """Manages all protocol connectors and provides a unified interface."""

    def __init__(self) -> None:
        self._connectors: dict[ProtocolType, BaseProtocolConnector] = {}

    def register(self, connector: BaseProtocolConnector) -> None:
        """Register a protocol connector."""
        self._connectors[connector.protocol_type] = connector
        log.info("registry.registered", protocol=connector.protocol_type.value,
                 direction=connector.direction.value)

    async def start_all(self) -> None:
        """Start all registered connectors."""
        for connector in self._connectors.values():
            await connector.start()

    async def stop_all(self) -> None:
        """Stop all registered connectors."""
        for connector in self._connectors.values():
            await connector.stop()

    def all_sessions(self) -> list[dict[str, Any]]:
        """Unified session list across all protocols."""
        sessions = []
        for connector in self._connectors.values():
            for info in connector.get_sessions():
                info.setdefault("protocol", connector.protocol_type.value)
                sessions.append(info)
        return sessions

    def get_connector(self, protocol: ProtocolType) -> BaseProtocolConnector | None:
        return self._connectors.get(protocol)

    @property
    def protocols(self) -> list[str]:
        return [p.value for p in self._connectors]

    async def list_files(self, machine_id: str, path: str = "") -> list[dict]:
        """Route file listing to the correct connector."""
        for connector in self._connectors.values():
            try:
                return await connector.list_files(machine_id, path)
            except KeyError:
                continue
        return []

    async def read_file(self, machine_id: str, path: str) -> bytes | None:
        """Route file read to the correct connector."""
        for connector in self._connectors.values():
            try:
                return await connector.read_file(machine_id, path)
            except KeyError:
                continue
        return None

    async def write_file(self, machine_id: str, path: str, data: bytes) -> bool:
        """Route file write to the correct connector."""
        for connector in self._connectors.values():
            try:
                return await connector.write_file(machine_id, path, data)
            except KeyError:
                continue
        return False
