"""CLI entry point for PCU20 Network Manager."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
import structlog

from pcu20 import __version__
from pcu20.config import load_config

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
)

log = structlog.get_logger()


@click.group(invoke_without_command=True)
@click.option("--config", "-c", type=click.Path(exists=False), default="pcu20.toml",
              help="Path to configuration file")
@click.version_option(version=__version__)
@click.pass_context
def main(ctx: click.Context, config: str) -> None:
    """PCU20 Network Manager — File server for Sinumerik CNC controllers."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config)

    if ctx.invoked_subcommand is None:
        ctx.invoke(serve)


@main.command()
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start the PCU20 server (TCP file server + web dashboard)."""
    config_path = ctx.obj["config_path"]
    cfg = load_config(config_path)
    log.info("config.loaded", path=str(config_path), shares=len(cfg.shares))

    from pcu20.app import run_app
    asyncio.run(run_app(cfg))


@main.command()
@click.pass_context
def init_config(ctx: click.Context) -> None:
    """Generate a default configuration file."""
    import shutil
    src = Path(__file__).parent.parent.parent / "pcu20.toml.example"
    dest = ctx.obj["config_path"]
    if dest.exists():
        click.confirm(f"{dest} already exists. Overwrite?", abort=True)
    if src.exists():
        shutil.copy(src, dest)
    else:
        import tomli_w
        from pcu20.config import AppConfig
        cfg = AppConfig()
        with open(dest, "wb") as f:
            tomli_w.dump(cfg.model_dump(), f)
    log.info("config.created", path=str(dest))


@main.command()
@click.option("--target-host", required=True, help="IP of the original PCU20 Network Manager")
@click.option("--target-port", type=int, default=6743, help="Port of the original server")
@click.option("--listen-port", type=int, default=6743, help="Port to listen on")
@click.option("--output", "-o", default="capture.bin", help="Output capture file")
def capture(target_host: str, target_port: int, listen_port: int, output: str) -> None:
    """Run MITM capture proxy for protocol reverse-engineering."""
    from tools.capture_proxy import run_capture_proxy
    asyncio.run(run_capture_proxy(target_host, target_port, listen_port, output))
