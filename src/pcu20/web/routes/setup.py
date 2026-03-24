"""Setup guide, network tools, and machine management routes."""

from __future__ import annotations

import asyncio
import re
import socket
import struct
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import structlog

from pcu20.config import FocasMachineConfig, save_config

log = structlog.get_logger()

router = APIRouter()


@router.get("/")
async def setup_page(request: Request):
    """Render the setup guide page."""
    config = request.app.state.config
    templates = request.app.state.templates

    server_ips = await asyncio.to_thread(_get_local_ips)

    return templates.TemplateResponse(request, "setup.html", {
        "server_ips": server_ips,
        "pcu20_config": config.pcu20,
        "focas_config": config.focas,
        "focas_machines": [m.model_dump() for m in config.focas.machines],
    })


@router.post("/api/scan")
async def api_network_scan(request: Request):
    """Scan a subnet for CNC machines on known ports."""
    body = await request.json()
    subnet = body.get("subnet", "")
    if not subnet:
        return JSONResponse({"error": "subnet required"}, status_code=400)

    results = await asyncio.to_thread(_scan_subnet, subnet)
    return {"subnet": subnet, "results": results}


@router.post("/api/test-connection")
async def api_test_connection(request: Request):
    """Test TCP connectivity to a specific host:port."""
    body = await request.json()
    host = body.get("host", "")
    port = body.get("port", 0)
    if not host or not port:
        return JSONResponse({"error": "host and port required"}, status_code=400)

    result = await asyncio.to_thread(_test_connection, host, int(port))
    return result


@router.post("/api/add-machine")
async def api_add_machine(request: Request):
    """Add a FOCAS2 machine to the configuration and save."""
    body = await request.json()
    machine_id = body.get("id", "").strip()
    name = body.get("name", "").strip()
    host = body.get("host", "").strip()
    port = int(body.get("port", 8193))
    cnc_type = body.get("cnc_type", "").strip()

    # Validate
    if not machine_id:
        return JSONResponse({"error": "Machine ID is required"}, status_code=400)
    if not host:
        return JSONResponse({"error": "Host IP is required"}, status_code=400)
    if not re.match(r'^[a-zA-Z0-9_-]+$', machine_id):
        return JSONResponse({"error": "ID must be alphanumeric (a-z, 0-9, -, _)"}, status_code=400)

    config = request.app.state.config

    # Check for duplicate ID
    for m in config.focas.machines:
        if m.id == machine_id:
            return JSONResponse({"error": f"Machine '{machine_id}' already exists"}, status_code=409)

    # Add the machine
    new_machine = FocasMachineConfig(
        id=machine_id,
        name=name or machine_id,
        host=host,
        port=port,
        cnc_type=cnc_type,
    )
    config.focas.machines.append(new_machine)
    config.focas.enabled = True

    # Save config
    config_path = Path("pcu20.toml")
    await asyncio.to_thread(save_config, config, config_path)

    # Register with machine registry if running
    machine_registry = request.app.state.machine_registry
    machine_registry.register_configured(
        machine_id=machine_id,
        ip=host,
        name=name or machine_id,
        protocol_type="focas2",
        cnc_type=cnc_type,
    )

    log.info("setup.machine_added", id=machine_id, host=host, cnc_type=cnc_type)
    return {"ok": True, "machine": new_machine.model_dump()}


@router.post("/api/remove-machine")
async def api_remove_machine(request: Request):
    """Remove a FOCAS2 machine from the configuration and save."""
    body = await request.json()
    machine_id = body.get("id", "").strip()

    if not machine_id:
        return JSONResponse({"error": "Machine ID is required"}, status_code=400)

    config = request.app.state.config

    # Find and remove
    original_count = len(config.focas.machines)
    config.focas.machines = [m for m in config.focas.machines if m.id != machine_id]

    if len(config.focas.machines) == original_count:
        return JSONResponse({"error": f"Machine '{machine_id}' not found"}, status_code=404)

    if not config.focas.machines:
        config.focas.enabled = False

    # Save config
    config_path = Path("pcu20.toml")
    await asyncio.to_thread(save_config, config, config_path)

    log.info("setup.machine_removed", id=machine_id)
    return {"ok": True}


@router.get("/api/machines")
async def api_configured_machines(request: Request):
    """List all configured FOCAS2 machines."""
    config = request.app.state.config
    return {
        "machines": [m.model_dump() for m in config.focas.machines],
        "focas_enabled": config.focas.enabled,
    }


@router.get("/api/server-info")
async def api_server_info(request: Request):
    """Return this server's network info for setup instructions."""
    config = request.app.state.config
    ips = await asyncio.to_thread(_get_local_ips)
    return {
        "ips": ips,
        "pcu20_ports": {
            "start": config.pcu20.base_port,
            "end": config.pcu20.base_port + config.pcu20.num_ports - 1,
        },
        "web_port": config.web.port,
    }


# --- Helper functions (run in thread) ---

def _get_local_ips() -> list[str]:
    """Get all non-loopback IPv4 addresses of this machine."""
    ips = []
    try:
        # Get all addresses by connecting to a dummy address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip and ip != "0.0.0.0":
                ips.append(ip)
        except Exception:
            pass
        finally:
            s.close()

        # Also try hostname resolution
        try:
            hostname = socket.gethostname()
            for addr_info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = addr_info[4][0]
                if ip not in ips and not ip.startswith("127."):
                    ips.append(ip)
        except Exception:
            pass
    except Exception:
        pass

    return ips or ["127.0.0.1"]


def _scan_subnet(subnet: str) -> list[dict]:
    """Scan a /24 subnet for CNC machines on known ports.

    Args:
        subnet: e.g. "192.168.1" (scans .1-.254) or "192.168.1.0/24"
    """
    # Parse subnet
    base = subnet.replace("/24", "").rstrip(".0").rstrip(".")
    parts = base.split(".")
    if len(parts) != 3:
        return []

    # Known CNC ports to check
    ports_to_scan = [
        (6743, "PCU20"),
        (8193, "FOCAS2"),
    ]

    results = []

    for host_part in range(1, 255):
        ip = f"{base}.{host_part}"
        for port, protocol in ports_to_scan:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.3)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    # Try to get hostname
                    try:
                        hostname = socket.gethostbyaddr(ip)[0]
                    except Exception:
                        hostname = ""

                    results.append({
                        "ip": ip,
                        "port": port,
                        "protocol": protocol,
                        "hostname": hostname,
                        "status": "open",
                    })
            except Exception:
                pass

    return results


def _test_connection(host: str, port: int) -> dict:
    """Test TCP connectivity and measure response time."""
    result = {
        "host": host,
        "port": port,
        "reachable": False,
        "latency_ms": None,
        "error": None,
    }

    # First test: ICMP-like reachability via TCP connect
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        elapsed = (time.time() - start) * 1000
        sock.close()
        result["reachable"] = True
        result["latency_ms"] = round(elapsed, 1)

        # Identify protocol by port
        if port in range(6743, 6758):
            result["protocol"] = "PCU20"
        elif port == 8193:
            result["protocol"] = "FOCAS2"
        else:
            result["protocol"] = "unknown"

    except socket.timeout:
        result["error"] = "Connection timed out (3s)"
    except ConnectionRefusedError:
        result["error"] = "Connection refused — port is closed"
    except OSError as e:
        result["error"] = f"Network error: {e}"

    return result
