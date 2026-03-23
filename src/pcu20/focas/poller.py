"""Async status polling loop for FOCAS2 machines."""

from __future__ import annotations

import asyncio

import structlog

from pcu20.event_bus import EventBus
from pcu20.focas.client import FocasClient
from pcu20.machines.registry import MachineRegistry

log = structlog.get_logger()


class FocasPoller:
    """Periodically polls all FOCAS machines for status, position, alarms."""

    def __init__(
        self,
        clients: dict[str, FocasClient],
        event_bus: EventBus,
        machine_registry: MachineRegistry,
        interval: float = 2.0,
    ) -> None:
        self._clients = clients
        self._event_bus = event_bus
        self._registry = machine_registry
        self._interval = interval

    async def run(self) -> None:
        """Main polling loop — runs until cancelled."""
        log.info("focas.poller_started", machines=len(self._clients),
                 interval=self._interval)

        while True:
            for machine_id, client in self._clients.items():
                if not client.is_connected:
                    continue
                try:
                    status = await asyncio.to_thread(client.read_status)
                    position = await asyncio.to_thread(client.read_absolute_pos)
                    program = await asyncio.to_thread(client.read_program_number)
                    alarms = await asyncio.to_thread(client.read_alarm)

                    status_data = {
                        "machine_id": machine_id,
                        "protocol": "focas2",
                        "status": status,
                        "position": position,
                        "program": program,
                        "alarms": alarms,
                    }

                    # Update machine registry
                    self._registry.update_status(machine_id, status_data)

                    # Emit event for WebSocket clients
                    self._event_bus.emit("machine.status", status_data)

                    # Emit alarm events
                    for alarm in alarms:
                        self._event_bus.emit("machine.alarm", {
                            "machine_id": machine_id,
                            "alarm_code": alarm.get("code"),
                            "message": alarm.get("message", ""),
                        })

                except Exception:
                    log.warning("focas.poll_error", machine_id=machine_id)
                    self._event_bus.emit("machine.error", {
                        "machine_id": machine_id,
                        "error": "poll_failed",
                    })

            await asyncio.sleep(self._interval)
