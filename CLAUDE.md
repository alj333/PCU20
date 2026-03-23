# CLAUDE.md — Agent Notes for PCU20 Network Manager

## What This Project Is

A modern Python replacement for "PCU20 Network Manager" by Stella Nova Industriapplikationer AB — a commercial Windows-only tool (.NET 4.0 GUI + Delphi Windows Service) that acts as a TCP file server for Siemens Sinumerik PCU20 CNC controllers (810D). The original installer is `pcu20net-setup.exe` in the repo root.

The PCU20 is a Linux-based embedded HMI for Sinumerik 810D/840D CNC machines. It connects over LAN to this software as a **client** to upload/download NC program files.

## Architecture

Single Python process running two concurrent servers on one asyncio event loop:

- **TCP File Server** (ports 6743–6757) — implements the PCU20 FTP protocol
- **Web Dashboard** (port 8020) — FastAPI + htmx/Alpine.js, real-time via WebSocket

An internal `EventBus` (`src/pcu20/event_bus.py`) bridges TCP events to WebSocket clients.

## Project Layout

```
src/pcu20/
├── cli.py              # Click CLI (entry point)
├── config.py           # Pydantic config models, loads pcu20.toml
├── app.py              # Orchestrator — starts TCP + web servers
├── event_bus.py        # Async pub/sub for internal events
├── protocol/           # PCU20 TCP protocol implementation
│   ├── server.py       # Multi-port asyncio TCP server
│   ├── codec.py        # Wire format framing (PROVISIONAL — needs real captures)
│   ├── session.py      # Per-connection state machine
│   ├── commands.py     # Command registry + dispatcher
│   ├── handlers.py     # File/dir operation handlers
│   ├── auth.py         # Login/password validation
│   ├── types.py        # Protocol enums, constants (PROVISIONAL command IDs)
│   └── discovery.py    # Unknown-command hex dump logger
├── storage/
│   ├── shares.py       # Virtual path → local filesystem mapping
│   ├── filesystem.py   # Sandboxed file I/O helpers
│   └── versioning.py   # Git-based NC program version tracking
├── machines/
│   ├── registry.py     # Connected machine tracking
│   └── models.py       # Machine data models
└── web/
    ├── app.py          # FastAPI factory
    ├── websocket.py    # WebSocket hub ↔ EventBus
    ├── routes/         # Page routes (dashboard, machines, shares, files, logs)
    ├── templates/      # Jinja2 + htmx templates
    └── static/         # CSS, JS (no build step, no Node.js)
tools/
├── capture_proxy.py    # MITM TCP proxy for protocol reverse-engineering
└── replay.py           # Replay captured sessions for testing
tests/                  # pytest (25 tests passing)
```

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"      # NOT -e (editable broken on Python 3.14 with hatchling)
python -m pcu20           # Start server
python -m pytest tests/   # Run tests
```

Note: On Python 3.14, `pip install -e` fails due to a hatchling `.pth` file processing issue. Use non-editable install and re-run `pip install ".[dev]"` after source changes.

## Key Commands

```bash
python -m pcu20                    # Start server (TCP + web)
python -m pcu20 --config my.toml   # Custom config file
python -m pcu20 init-config        # Generate default pcu20.toml
python -m pcu20 capture --target-host <IP>  # MITM capture proxy
```

## Critical: Protocol Is Provisional

**The wire format in `protocol/codec.py` and command IDs in `protocol/types.py` are educated guesses.** They have NOT been validated against a real PCU20. The actual binary framing, command IDs, and payload formats must be discovered by:

1. Running `capture_proxy.py` between a real PCU20 and the original Stella Nova software
2. Analyzing the hex dumps to determine the real frame format
3. Updating `codec.py` (framing), `types.py` (command IDs), and `handlers.py` (payload parsing)

The protocol discovery module (`discovery.py`) logs all unknown commands with full hex dumps to help with this.

### What we know from reverse-engineering the installer:
- Ports 6743–6757 (registered as `pcu20_ftp1` through `pcu20_ftp15`)
- PC is the **server**, CNC connects as **client**
- Custom binary protocol (NOT standard FTP despite the port names)
- Commands: Login, ReadFileFromServer, WriteFileToServer, ReadDirFromServer, GetDirList, MkDir, RmDir, StatFile, ChModFile, AccessFile, SearchInFile, GetFreeMem, GetVersion, TerminateConnect
- Password-based auth (default user `PCU20_USER`)
- PCU20 uses Linux internally (paths use `/`)
- The original Delphi service logged to `nwmtrace.log`

## Starlette/Jinja2 Note

Template responses use the newer Starlette API: `templates.TemplateResponse(request, "name.html", context)` — with `request` as the first arg, not inside the context dict. This is required on recent Starlette versions (Python 3.14 compatibility).

## What's Left to Build

### Phase 1 (protocol validation)
- Run MITM capture against real hardware
- Update codec with real frame format
- Validate/fix all command handlers against real traffic
- Add replay-based integration tests from captured sessions

### Phase 2 (features)
- File upload/download from the web UI
- Share management CRUD via web UI (currently config-file only)
- NC program diff viewer in version history
- Machine naming/labeling in the web UI

### Phase 3 (production)
- systemd unit file for Linux deployment
- Windows service support (nssm)
- Docker image
- TLS support for the web dashboard
- Authentication for the web dashboard
