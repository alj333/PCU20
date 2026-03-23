"""Setup guide and network tools routes."""

from __future__ import annotations

import asyncio
import socket
import struct
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import structlog

log = structlog.get_logger()

router = APIRouter()


@router.get("/")
async def setup_page(request: Request):
    """Render the setup guide page."""
    config = request.app.state.config
    templates = request.app.state.templates

    # Detect this server's IP addresses
    server_ips = await asyncio.to_thread(_get_local_ips)

    return templates.TemplateResponse(request, "setup.html", {
        "server_ips": server_ips,
        "pcu20_config": config.pcu20,
        "focas_config": config.focas,
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
