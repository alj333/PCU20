"""FOCAS2 connector — manages connections to Fanuc/Mori CNC machines."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from pcu20.config import FocasConfig
from pcu20.event_bus import EventBus
from pcu20.focas.client import FocasClient
from pcu20.focas.poller import FocasPoller
from pcu20.machines.registry import MachineRegistry
from pcu20.protocol.base import BaseProtocolConnector, ConnectionDirection, ProtocolType
from pcu20.storage.shares import ShareManager
from pcu20.storage.versioning import VersionManager

log = structlog.get_logger()


class FocasConnector(BaseProtocolConnector):
    """Manages outbound FOCAS2 connections to Fanuc/Mori CNC machines."""

    protocol_type = ProtocolType.FOCAS2
    direction = ConnectionDirection.OUTBOUND

    def __init__(
        self,
        config: FocasConfig,
        event_bus: EventBus,
        machine_registry: MachineRegistry,
        share_manager: ShareManager,
        version_manager: VersionManager,
    ) -> None:
        self.config = config
        self._event_bus = event_bus
        self._registry = machine_registry
        self._share_manager = share_manager
        self._version_manager = version_manager
        self._clients: dict[str, FocasClient] = {}
        self._poll_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Connect to all configured FOCAS machines and start polling."""
        for machine_cfg in self.config.machines:
            if not machine_cfg.enabled:
                continue

            # Register the machine from config
            self._registry.register_configured(
                machine_id=machine_cfg.id,
                ip=machine_cfg.host,
                name=machine_cfg.name or machine_cfg.id,
                protocol_type="focas2",
                cnc_type=machine_cfg.cnc_type,
            )

            # Create client and attempt connection
            client = FocasClient(machine_cfg.host, machine_cfg.port)
            try:
                await asyncio.to_thread(client.connect)
                self._clients[machine_cfg.id] = client

                self._registry.on_connect(
                    machine_cfg.host, machine_cfg.id,
                    machine_id=machine_cfg.id, protocol_type="focas2",
                )

                self._event_bus.emit("machine.connected", {
                    "machine_id": machine_cfg.id,
                    "ip": machine_cfg.host,
                    "protocol": "focas2",
                    "name": machine_cfg.name,
                    "cnc_type": machine_cfg.cnc_type,
                })

                log.info("focas.connected", machine_id=machine_cfg.id,
                         host=machine_cfg.host, cnc_type=machine_cfg.cnc_type)
            except Exception as e:
                log.error("focas.connect_failed", machine_id=machine_cfg.id,
                          host=machine_cfg.host, error=str(e))

        # Start status poller if we have connected clients
        if self._clients:
            poller = FocasPoller(
                self._clients, self._event_bus, self._registry,
                interval=self.config.poll_interval,
            )
            self._poll_task = asyncio.create_task(poller.run())

        log.info("focas.started", connected=len(self._clients),
                 configured=len(self.config.machines))

    async def stop(self) -> None:
        """Stop polling and disconnect from all machines."""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        for machine_id, client in self._clients.items():
            try:
                await asyncio.to_thread(client.disconnect)
            except Exception:
                pass
            self._registry.on_disconnect(machine_id)
            self._event_bus.emit("machine.disconnected", {
                "machine_id": machine_id,
                "protocol": "focas2",
            })

        self._clients.clear()
        log.info("focas.stopped")

    def get_sessions(self) -> list[dict[str, Any]]:
        """Return connected FOCAS machine summaries as 'sessions'."""
        sessions = []
        for machine_id, client in self._clients.items():
            machine = self._registry.get(machine_id)
            if machine:
                info = machine.summary()
                info["protocol"] = "focas2"
                sessions.append(info)
        return sessions

    async def list_files(self, machine_id: str, path: str = "") -> list[dict]:
        """List programs on a FOCAS machine."""
        client = self._clients.get(machine_id)
        if client is None:
            raise KeyError(f"Unknown FOCAS machine: {machine_id}")
        return await asyncio.to_thread(client.read_program_directory)

    async def read_file(self, machine_id: str, path: str) -> bytes | None:
        """Upload a program from a FOCAS machine."""
        client = self._clients.get(machine_id)
        if client is None:
            raise KeyError(f"Unknown FOCAS machine: {machine_id}")
        try:
            prog_number = int(path.lstrip("O").split(".")[0])
        except (ValueError, IndexError):
            return None
        return await asyncio.to_thread(client.upload_file, prog_number)

    async def write_file(self, machine_id: str, path: str, data: bytes) -> bool:
        """Download a program to a FOCAS machine."""
        client = self._clients.get(machine_id)
        if client is None:
            raise KeyError(f"Unknown FOCAS machine: {machine_id}")
        try:
            prog_number = int(path.lstrip("O").split(".")[0])
        except (ValueError, IndexError):
            return False
        return await asyncio.to_thread(client.download_file, data, prog_number)
