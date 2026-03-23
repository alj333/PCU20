"""Application orchestrator — starts protocol connectors and web dashboard."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import structlog

from pcu20.config import AppConfig
from pcu20.event_bus import EventBus
from pcu20.machines.registry import MachineRegistry
from pcu20.protocol.registry import ConnectorRegistry
from pcu20.storage.shares import ShareManager
from pcu20.storage.versioning import VersionManager

log = structlog.get_logger()


async def run_app(config: AppConfig) -> None:
    """Main application entry point — runs protocol connectors and web server."""
    event_bus = EventBus()
    share_manager = ShareManager(config.shares)
    version_manager = VersionManager(config.versioning)
    machine_registry = MachineRegistry()

    # Initialize versioning for each share
    for share in config.shares:
        version_manager.init_share(Path(share.path))

    # Build connector registry
    connector_registry = ConnectorRegistry()

    # PCU20 connector (inbound TCP server)
    if config.pcu20.enabled:
        from pcu20.protocol.server import PCU20Server
        pcu20_server = PCU20Server(
            config=config,
            event_bus=event_bus,
            share_manager=share_manager,
            version_manager=version_manager,
            machine_registry=machine_registry,
        )
        connector_registry.register(pcu20_server)

    # FOCAS2 connector (outbound client) — enabled when configured
    if config.focas.enabled and config.focas.machines:
        try:
            from pcu20.focas.connector import FocasConnector
            focas_connector = FocasConnector(
                config=config.focas,
                event_bus=event_bus,
                machine_registry=machine_registry,
                share_manager=share_manager,
                version_manager=version_manager,
            )
            connector_registry.register(focas_connector)
        except ImportError:
            log.warning("focas.not_available",
                        msg="FOCAS2 module dependencies not installed. "
                            "Install with: pip install pcu20[focas]")

    await connector_registry.start_all()

    # Start web dashboard if enabled
    web_task = None
    if config.web.enabled:
        from pcu20.web.app import create_web_app
        import uvicorn

        fastapi_app = create_web_app(
            connector_registry=connector_registry,
            event_bus=event_bus,
            share_manager=share_manager,
            version_manager=version_manager,
            machine_registry=machine_registry,
            config=config,
        )

        uvicorn_config = uvicorn.Config(
            app=fastapi_app,
            host=config.web.host,
            port=config.web.port,
            log_level="warning",
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)

        web_task = asyncio.create_task(uvicorn_server.serve())
        log.info("web.started", host=config.web.host, port=config.web.port,
                 url=f"http://localhost:{config.web.port}")

    # Handle shutdown signals
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("shutdown.signal_received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    log.info(
        "app.ready",
        protocols=connector_registry.protocols,
        web_port=config.web.port if config.web.enabled else "disabled",
        shares=len(config.shares),
    )

    # Wait for shutdown
    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

    # Cleanup
    log.info("app.shutting_down")
    await connector_registry.stop_all()
    if web_task:
        web_task.cancel()
        try:
            await web_task
        except asyncio.CancelledError:
            pass

    log.info("app.stopped")
