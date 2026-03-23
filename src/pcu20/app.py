"""Application orchestrator — starts TCP server and web dashboard."""

from __future__ import annotations

import asyncio
import signal

import structlog

from pcu20.config import AppConfig
from pcu20.event_bus import EventBus
from pcu20.machines.registry import MachineRegistry
from pcu20.protocol.server import PCU20Server
from pcu20.storage.shares import ShareManager
from pcu20.storage.versioning import VersionManager

log = structlog.get_logger()


async def run_app(config: AppConfig) -> None:
    """Main application entry point — runs both TCP and web servers."""
    event_bus = EventBus()
    share_manager = ShareManager(config.shares)
    version_manager = VersionManager(config.versioning)
    machine_registry = MachineRegistry()

    # Initialize versioning for each share
    from pathlib import Path
    for share in config.shares:
        version_manager.init_share(Path(share.path))

    # Create the TCP server
    tcp_server = PCU20Server(
        config=config,
        event_bus=event_bus,
        share_manager=share_manager,
        version_manager=version_manager,
        machine_registry=machine_registry,
    )

    await tcp_server.start()

    # Start web dashboard if enabled
    web_task = None
    if config.web.enabled:
        from pcu20.web.app import create_web_app
        import uvicorn

        fastapi_app = create_web_app(
            tcp_server=tcp_server,
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
            # Windows doesn't support add_signal_handler
            pass

    log.info(
        "app.ready",
        tcp_ports=f"{config.server.base_port}-{config.server.base_port + config.server.num_ports - 1}",
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
    await tcp_server.stop()
    if web_task:
        web_task.cancel()
        try:
            await web_task
        except asyncio.CancelledError:
            pass

    log.info("app.stopped")
