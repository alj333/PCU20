"""Asyncio multi-port TCP server for PCU20 protocol."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from pcu20.config import AppConfig
from pcu20.event_bus import EventBus
from pcu20.machines.registry import MachineRegistry
from pcu20.protocol.auth import Authenticator
from pcu20.protocol.codec import FrameCodec
from pcu20.protocol.commands import CommandRegistry
from pcu20.protocol.discovery import ProtocolDiscovery
from pcu20.protocol.handlers import Handlers
from pcu20.protocol.session import Session
from pcu20.protocol.types import CommandId
from pcu20.storage.shares import ShareManager
from pcu20.storage.versioning import VersionManager

log = structlog.get_logger()


class PCU20Server:
    """Multi-port asyncio TCP server implementing the PCU20 file protocol."""

    def __init__(
        self,
        config: AppConfig,
        event_bus: EventBus,
        share_manager: ShareManager,
        version_manager: VersionManager,
        machine_registry: MachineRegistry,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.share_manager = share_manager
        self.version_manager = version_manager
        self.machine_registry = machine_registry

        self.sessions: dict[str, Session] = {}
        self._servers: list[asyncio.Server] = []

        # Set up protocol components
        self._discovery = ProtocolDiscovery(
            trace_file=config.logging.trace_file if config.logging.protocol_trace else None,
            enabled=config.logging.protocol_trace,
        )
        self._authenticator = Authenticator(config.auth)
        self._handlers = Handlers(self._authenticator, share_manager, version_manager)
        self._commands = CommandRegistry(self._discovery)

        # Register command handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register all known command handlers."""
        h = self._handlers
        reg = self._commands.register

        # Auth
        reg(CommandId.LOGIN, "Login", h.handle_login)
        reg(CommandId.TERMINATE, "Terminate", h.handle_terminate)

        # File operations
        reg(CommandId.READ_FILE, "ReadFile", h.handle_read_file)
        reg(CommandId.WRITE_FILE, "WriteFile", h.handle_write_file)
        reg(CommandId.STAT_FILE, "StatFile", h.handle_stat_file)

        # Directory operations
        reg(CommandId.READ_DIR, "ReadDir", h.handle_read_dir)
        reg(CommandId.MKDIR, "MkDir", h.handle_mkdir)
        reg(CommandId.RMDIR, "RmDir", h.handle_rmdir)

        # System queries
        reg(CommandId.GET_FREE_MEM, "GetFreeMem", h.handle_get_free_mem)
        reg(CommandId.GET_VERSION, "GetVersion", h.handle_get_version)
        reg(CommandId.GET_VERSION_EX, "GetVersion", h.handle_get_version)

    async def start(self) -> None:
        """Start listening on all configured ports."""
        self._discovery.start()

        base = self.config.server.base_port
        num = self.config.server.num_ports
        bind = self.config.server.bind_address

        for port in range(base, base + num):
            server = await asyncio.start_server(
                self._handle_connection,
                host=bind,
                port=port,
            )
            self._servers.append(server)
            log.info("server.listening", host=bind, port=port)

        log.info(
            "server.started",
            ports=f"{base}-{base + num - 1}",
            commands=self._commands.registered_commands,
        )

    async def stop(self) -> None:
        """Stop all TCP servers and close all sessions."""
        for server in self._servers:
            server.close()
            await server.wait_closed()

        for session in list(self.sessions.values()):
            session.close_all_handles()
            session.disconnect()

        self.sessions.clear()
        self._servers.clear()
        self._discovery.stop()
        log.info("server.stopped")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single CNC connection."""
        peer = writer.get_extra_info("peername")
        local = writer.get_extra_info("sockname")

        session = Session(peer_address=peer)
        self.sessions[session.id] = session
        machine = self.machine_registry.on_connect(session.peer_ip, session.id)

        log.info(
            "connection.new",
            session=session.id[:8],
            peer=f"{peer[0]}:{peer[1]}",
            local_port=local[1] if local else "?",
        )
        self.event_bus.emit("machine.connected", session.summary())

        codec = FrameCodec()
        idle_timeout = 300  # 5 minutes
        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(65536), timeout=idle_timeout)
                except asyncio.TimeoutError:
                    log.info("connection.idle_timeout", session=session.id[:8])
                    break
                if not data:
                    break

                session.bytes_received += len(data)
                self._discovery.log_raw(session.id, "C2S", data)

                for frame in codec.feed(data):
                    response = await self._commands.dispatch(session, frame)
                    if response:
                        self._discovery.log_raw(session.id, "S2C", response)
                        writer.write(response)
                        await writer.drain()
                        session.bytes_sent += len(response)

                # Emit transfer progress events
                self.event_bus.emit("session.activity", session.summary())

                # Check if session was terminated by a handler
                if session.state.value == "disconnected":
                    break

        except ConnectionResetError:
            log.info("connection.reset", session=session.id[:8])
        except Exception:
            log.exception("connection.error", session=session.id[:8])
        finally:
            session.close_all_handles()
            session.disconnect()
            self.sessions.pop(session.id, None)

            self.machine_registry.on_disconnect(
                session.peer_ip,
                bytes_transferred=session.bytes_sent + session.bytes_received,
                files_transferred=session.files_transferred,
            )

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            log.info(
                "connection.closed",
                session=session.id[:8],
                peer=session.peer_ip,
                commands=session.commands_processed,
                files=session.files_transferred,
                bytes_total=session.bytes_sent + session.bytes_received,
            )
            self.event_bus.emit("machine.disconnected", session.summary())

    @property
    def active_sessions(self) -> list[dict[str, Any]]:
        return [s.summary() for s in self.sessions.values()]
