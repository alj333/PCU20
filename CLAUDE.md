# CLAUDE.md — Agent Notes for CNC Network Manager

## What This Project Is

A multi-protocol CNC communication platform that started as a replacement for "PCU20 Network Manager" by Stella Nova Industriapplikationer AB. It now supports multiple CNC protocols through a unified web dashboard. The original Sinumerik PCU20 installer is `pcu20net-setup.exe` in the repo root.

**Supported CNC types:**
- **Sinumerik PCU20 (810D)** — custom TCP protocol, ports 6743–6757, inbound (CNC connects to us)
- **Fanuc 30i, 16i, 0i-MD** — FOCAS2 protocol, port 8193, outbound (we connect to CNC)
- **Mori MAPPS (Fanuc 31i)** — FOCAS2 protocol (same as Fanuc, MAPPS is a UI layer)
- **LinuxCNC** — future, extensible via `BaseProtocolConnector`

## Architecture

```
ConnectorRegistry (unified interface)
├── PCU20Server (BaseProtocolConnector) — inbound TCP, ports 6743-6757
├── FocasConnector (BaseProtocolConnector) — outbound client, port 8193
└── (future: LinuxCNCConnector, etc.)
        │
        ▼
Shared infrastructure:
  EventBus, ShareManager, VersionManager, MachineRegistry
        │
        ▼
  Web Dashboard (protocol-aware, FastAPI + htmx/Alpine.js)
```

Key architectural pattern: `BaseProtocolConnector` ABC handles both inbound (CNC connects to us) and outbound (we connect to CNC) connection models through a uniform `start/stop/get_sessions/list_files/read_file/write_file` interface.

## Project Layout

```
src/pcu20/
├── cli.py              # Click CLI (entry point)
├── config.py           # Pydantic config: PCU20Config, FocasConfig, AppConfig
├── app.py              # Orchestrator — builds ConnectorRegistry, starts all
├── event_bus.py        # Async pub/sub for internal events
├── protocol/           # Protocol abstraction + PCU20 implementation
│   ├── base.py         # BaseProtocolConnector ABC, ProtocolType, CNCStatus enums
│   ├── registry.py     # ConnectorRegistry — manages all protocol connectors
│   ├── server.py       # PCU20Server(BaseProtocolConnector) — inbound TCP
│   ├── codec.py        # PCU20 wire format framing (PROVISIONAL)
│   ├── session.py      # Per-connection state machine
│   ├── commands.py     # Command registry + dispatcher
│   ├── handlers.py     # PCU20 file/dir operation handlers
│   ├── auth.py         # Login/password validation
│   ├── types.py        # PCU20 protocol enums, constants (PROVISIONAL)
│   └── discovery.py    # Unknown-command hex dump logger
├── focas/              # FOCAS2 protocol module (Fanuc/Mori)
│   ├── client.py       # FocasClient — low-level wrapper (pyfocas ctypes or pyfanuc)
│   ├── connector.py    # FocasConnector(BaseProtocolConnector) — outbound client
│   ├── poller.py       # FocasPoller — async status polling loop
│   └── types.py        # FOCAS2-specific enums (FocasRunState, FocasMode, etc.)
├── storage/
│   ├── shares.py       # Virtual path → local filesystem mapping (protocol-agnostic)
│   ├── filesystem.py   # Sandboxed file I/O helpers
│   └── versioning.py   # Git-based NC program version tracking (protocol-agnostic)
├── machines/
│   ├── registry.py     # Machine tracking by machine_id (supports all protocols)
│   └── models.py       # Machine model with protocol_type + live CNC status fields
└── web/
    ├── app.py          # FastAPI factory (uses ConnectorRegistry, not tcp_server)
    ├── websocket.py    # WebSocket hub ↔ EventBus
    ├── routes/         # Page routes (dashboard, machines, shares, files, logs)
    ├── templates/      # Jinja2 + htmx templates
    └── static/         # CSS, JS (no build step, no Node.js)
tools/
├── capture_proxy.py    # MITM TCP proxy for PCU20 protocol reverse-engineering
└── replay.py           # Replay captured sessions for testing
tests/                  # pytest (25 tests passing)
```

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"           # Core + dev tools
pip install ".[dev,focas]"     # Also install FOCAS2 library (if available)
python -m pcu20                # Start server
python -m pytest tests/        # Run tests
```

Note: On Python 3.14, `pip install -e` fails due to a hatchling `.pth` file processing issue. Use non-editable install and re-run `pip install ".[dev]"` after source changes.

## Key Commands

```bash
python -m pcu20                    # Start server (all enabled protocols + web)
python -m pcu20 --config my.toml   # Custom config file
python -m pcu20 init-config        # Generate default pcu20.toml
python -m pcu20 capture --target-host <IP>  # MITM capture proxy (PCU20)
```

## Config Structure

The config uses `[pcu20]` for Sinumerik and `[focas]` for Fanuc/Mori. Old `[server]` key is auto-mapped to `[pcu20]` for backward compatibility.

```toml
[pcu20]
enabled = true
base_port = 6743
num_ports = 15

[focas]
enabled = true
poll_interval = 2.0

[[focas.machines]]
id = "fanuc-30i"
name = "Fanuc 30i-Model A"
host = "192.168.1.50"
cnc_type = "fanuc-30i"

[[focas.machines]]
id = "mori-mapps"
name = "Mori NL2500"
host = "192.168.1.53"
cnc_type = "mori-mapps"

[web]
enabled = true
port = 8020

[[shares]]
name = "NCDATA"
path = "./ncdata"
```

## Adding a New Protocol Connector

To add support for a new CNC type (e.g., LinuxCNC):

1. Create `src/pcu20/yourproto/connector.py` inheriting `BaseProtocolConnector`
2. Implement: `start()`, `stop()`, `get_sessions()`, `list_files()`, `read_file()`, `write_file()`
3. Set `protocol_type` (add to `ProtocolType` enum in `protocol/base.py`) and `direction`
4. Add config class to `config.py` and field to `AppConfig`
5. Wire into `app.py` with conditional `connector_registry.register()`
6. The web dashboard, event bus, share manager, and versioning work automatically

## Critical: PCU20 Protocol Is Provisional

**The wire format in `protocol/codec.py` and command IDs in `protocol/types.py` are educated guesses.** They have NOT been validated against a real PCU20. Discover the real protocol by:

1. Running `capture_proxy.py` between a real PCU20 and the original Stella Nova software
2. Analyzing hex dumps to determine the real frame format
3. Updating `codec.py`, `types.py`, and `handlers.py`

## FOCAS2 Client Status

The `focas/client.py` methods are **stubs** awaiting real hardware testing. The architecture (connector, poller, event integration) is fully wired — just needs:
1. Install `pyfocas` (ctypes wrapper) or `pyfanuc` (pure Python)
2. Fill in `FocasClient` methods with actual FOCAS2 API calls
3. Test against a real Fanuc 30i first (most capable, best documented)

The client auto-detects available backends: tries `pyfocas` → `pyfanuc` → disables with clear error.

## Dashboard & Web UI

The dashboard (`v0.2.0`, branded "CNC Network Manager") is protocol-aware:

- **Machine fleet grid**: One card per machine with protocol badge (PCU20 purple / FOCAS2 blue), connection dot, CNC status indicator, mode, program number, live axis positions, and inline alarms. Cards update in real-time via WebSocket `machine.status` events.
- **Alarm banner**: Red pulsing banner auto-appears when any machine has active alarms. Tracks alarm state in JS `activeAlarms` object keyed by `machine_id`.
- **Machine cards have `id="machine-{machine_id}"`** so `app.js` can target them for live updates. If adding new machine card elements, keep this convention.
- **CNC status CSS classes**: `machine-cnc-status--running` (green), `--idle` (blue), `--alarm` (red), `--stopped` (amber), `--unknown` (grey). Match the `CNCStatus` enum values.
- **Machines page**: Shows protocol, CNC type, status, and program columns. Axis position section for connected FOCAS machines.
- **Activity feed filters out `machine.status`** events (too frequent) — only shows connects, disconnects, alarms, and file transfers.

### WebSocket event flow
- Dashboard page opens one persistent WS via `app.js` `connectWebSocket()`.
- Logs page opens one WS via htmx `ws-connect="/ws"` for the Alpine `logViewer` component.
- Other pages only probe WS for server status (connect then immediately close).
- Never add `hx-ext="ws" ws-connect="/ws"` AND use `app.js` WS on the same page.

## Code Patterns & Gotchas

- **Multi-protocol routing**: Web routes use `request.app.state.connector_registry` (not `tcp_server`). `ConnectorRegistry.all_sessions()` returns unified sessions across all protocols.
- **Machine IDs**: PCU20 machines use IP as their ID (discovered on connect). FOCAS machines use the config-defined `id` field (known at startup). `MachineRegistry` keys by `machine_id`.
- **Config backward compat**: Old `[server]` key auto-maps to `[pcu20]` via Pydantic `model_validator`.
- **Starlette TemplateResponse API**: Use `templates.TemplateResponse(request, "name.html", context)` — `request` is first arg, not in context dict.
- **Blocking I/O in async**: All file ops and FOCAS2 calls use `asyncio.to_thread()`. Follow this pattern for any new blocking code.
- **`_require_auth` takes `command_id`**: Pass the command's ID so error responses have the correct ID.
- **Path traversal protection**: `shares.py` uses `Path.is_relative_to()`. Always resolve paths through `ShareManager.resolve()`.
- **Password comparison**: `auth.py` uses `hmac.compare_digest()`. Don't switch to `==`.
- **Idle timeout**: PCU20 TCP connections time out after 5 minutes.
- **Session cleanup**: Use `.pop(id, None)` not `del` — the latter races with `stop()`.

## Known Remaining Issues

- **Test coverage is low** — 25 tests covering codec, session, shares only. No tests for: auth, handlers, commands, server, FOCAS module, versioning, machines, event_bus, config, web routes.
- **FOCAS2 client is stubs** — needs real hardware to implement actual API calls.
- **No web dashboard authentication** — all routes are public (acceptable for LAN-only use).
- **`app.js` connected count can drift** — should periodically fetch true count from API.
- **File transfer UI for FOCAS** — not yet built; machines page shows status but no upload/download buttons.

## What's Left to Build

### PCU20 protocol validation
- Run MITM capture against real hardware
- Update codec with real frame format
- Add replay-based integration tests

### FOCAS2 implementation
- Fill in FocasClient methods with real FOCAS2 API calls
- Test against Fanuc 30i, then 16i, 0i-MD, Mori MAPPS
- FOCAS2 reconnection with exponential backoff

### Features
- File transfer UI for FOCAS machines (upload/download buttons per machine)
- NC program diff viewer in version history
- Share management CRUD via web UI

### Production hardening
- Expand test coverage
- systemd unit / Docker image
- LinuxCNC connector (future)
