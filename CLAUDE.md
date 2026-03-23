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

## Code Patterns & Gotchas

- **Starlette TemplateResponse API**: Use `templates.TemplateResponse(request, "name.html", context)` — `request` is the first arg, not inside the context dict. Required on recent Starlette (Python 3.14 compatibility).
- **Blocking I/O in async handlers**: All file operations in `handlers.py` use `asyncio.to_thread()` to avoid blocking the event loop. Follow this pattern for any new handlers that do filesystem or git operations.
- **`_require_auth` takes `command_id`**: When adding new handlers, pass the command's ID so error responses have the correct command ID: `if err := _require_auth(session, CommandId.YOUR_CMD): return err`.
- **Path traversal protection**: `shares.py` uses `Path.is_relative_to()` (not `startswith()`). Never bypass this — always resolve paths through `ShareManager.resolve()`.
- **Password comparison**: `auth.py` uses `hmac.compare_digest()` to prevent timing side-channels. Don't switch to `==`.
- **Versioning is wired into handlers**: `handle_write_file` calls `self.versions.on_file_written()` after each CNC write. Git/snapshot ops run in a thread executor via `asyncio.to_thread()`.
- **Config validation**: `logging.level` and `versioning.strategy` use regex validators. Invalid values are rejected at config load, not silently ignored.
- **WebSocket per page**: Only the dashboard page opens a persistent WebSocket (via `app.js`). The logs page uses htmx `ws-connect` for its own stream. Other pages just probe for server status. Don't add `hx-ext="ws" ws-connect="/ws"` to templates — it creates duplicate connections.
- **Idle timeout**: TCP connections time out after 5 minutes of inactivity (`server.py`). The CNC must send data within this window.
- **Session cleanup**: Use `self.sessions.pop(id, None)` not `del self.sessions[id]` — the latter races with `stop()` during shutdown.

## Completed Audit Fixes (commit 19c279d)

A deep code audit identified 30+ issues. The following 17 were fixed:

**Critical:**
1. Path traversal bypass — `startswith()` replaced with `Path.is_relative_to()`
2. Blocking I/O in all async handlers — wrapped in `asyncio.to_thread()`
3. Version manager was disconnected — now wired into `Handlers` and called on file writes
4. `_require_auth` returned command_id=0 — now takes the actual command ID as parameter
5. Session dict `KeyError` on shutdown — `del` replaced with `.pop(session.id, None)`
6. No idle timeout — added 5-minute `asyncio.wait_for` on TCP reads

**Security:**
7. Timing side-channel — password comparison uses `hmac.compare_digest()`
8. Login payload truncated to 256 chars to prevent memory abuse

**Robustness:**
9. Codec frame resync — skips 1 byte on invalid frame instead of discarding entire buffer
10. Versioning root walk — bounded to known share roots (no walk to `/`)
11. Versioning I/O — git/snapshot ops run in thread executor
12. Config validation — `logging.level` and `versioning.strategy` validated with regex
13. CLI — log level from config now actually applied; capture import works when installed

**Web:**
14. Duplicate WebSocket connections — removed htmx `ws-connect` from dashboard; `app.js` only opens WS on dashboard page
15. Dashboard ports — sourced from config instead of hardcoded `6743`
16. Machines `last_seen` — formatted as date instead of raw Unix timestamp
17. API 404s — file/history routes return proper HTTP 404 instead of 200

## Known Remaining Issues (from audit, not yet fixed)

- **Test coverage is low** — only codec, session, and shares have tests (25 total). No tests for: auth, handlers, commands, server, versioning, machines, event_bus, config loading, web routes, WebSocket. Zero async tests despite async-first codebase.
- **No web dashboard authentication** — all routes are public (acceptable for LAN-only use).
- **`filesystem.py` is unused** — handlers implement file I/O inline. Could be removed or handlers refactored to use it.
- **CDN scripts without SRI hashes** — htmx/Alpine.js loaded without integrity attributes.
- **`app.js` connected count can drift** — increment/decrement logic desyncs if WebSocket events are missed. Should periodically fetch true count from API.
- **`discovery.py` unused `TYPE_CHECKING` import** — `Session` imported but never referenced in annotations.

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
- Expand test coverage (auth, handlers, web routes, async integration tests)

### Phase 3 (production)
- systemd unit file for Linux deployment
- Windows service support (nssm)
- Docker image
- TLS support for the web dashboard
- Authentication for the web dashboard (if needed beyond LAN)
