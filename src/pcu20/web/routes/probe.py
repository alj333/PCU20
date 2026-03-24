"""Probe setup, G-code generation, and drip feed routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import structlog

from pcu20.serial.drip_feed import DripFeeder, list_serial_ports

log = structlog.get_logger()

router = APIRouter()

# Active drip feed sessions (keyed by a simple session counter)
_drip_sessions: dict[int, DripFeeder] = {}
_tcp_sessions: dict[int, object] = {}
_session_counter = 0


@router.get("/")
async def probe_page(request: Request):
    """Render the probe setup page."""
    templates = request.app.state.templates
    machine_registry = request.app.state.machine_registry

    machines = [
        m for m in machine_registry.list_all()
        if m.get("protocol_type") == "focas2"
    ]

    serial_ports = await asyncio.to_thread(list_serial_ports)

    return templates.TemplateResponse(request, "probe.html", {
        "machines": machines,
        "serial_ports": serial_ports,
    })


@router.get("/api/serial-ports")
async def api_serial_ports():
    """List available serial ports."""
    ports = await asyncio.to_thread(list_serial_ports)
    return {"ports": ports}


@router.post("/api/drip-feed/serial")
async def api_drip_feed_serial(request: Request):
    """Send G-code via RS-232 drip feed."""
    global _session_counter
    body = await request.json()
    gcode = body.get("gcode", "")
    port = body.get("port", "")
    baud = int(body.get("baud", 9600))
    stop_bits = int(body.get("stop_bits", 2))
    parity = body.get("parity", "none")

    if not gcode:
        return JSONResponse({"error": "G-code required"}, status_code=400)
    if not port:
        return JSONResponse({"error": "Serial port required"}, status_code=400)

    feeder = DripFeeder(
        port=port,
        baud_rate=baud,
        stop_bits=stop_bits,
        parity=parity,
    )

    _session_counter += 1
    session_id = _session_counter
    _drip_sessions[session_id] = feeder

    # Run in background thread
    asyncio.get_event_loop().run_in_executor(None, feeder.send_sync, gcode)

    log.info("drip_feed.serial_started", port=port, baud=baud, session=session_id)
    return {"session_id": session_id, "state": "started"}


@router.post("/api/drip-feed/tcp")
async def api_drip_feed_tcp(request: Request):
    """Send G-code via TCP/LAN drip feed unit."""
    global _session_counter
    body = await request.json()
    gcode = body.get("gcode", "")
    host = body.get("host", "")
    port = int(body.get("port", 9100))

    if not gcode:
        return JSONResponse({"error": "G-code required"}, status_code=400)
    if not host:
        return JSONResponse({"error": "Host required"}, status_code=400)

    from pcu20.serial.tcp_drip import TCPDripFeeder
    feeder = TCPDripFeeder(host=host, port=port)

    _session_counter += 1
    session_id = _session_counter
    _tcp_sessions[session_id] = feeder

    # Run as async task
    asyncio.create_task(feeder.send(gcode))

    log.info("drip_feed.tcp_started", host=host, port=port, session=session_id)
    return {"session_id": session_id, "state": "started"}


@router.get("/api/drip-feed/status/{session_id}")
async def api_drip_feed_status(session_id: int):
    """Get drip feed session status."""
    feeder = _drip_sessions.get(session_id) or _tcp_sessions.get(session_id)
    if not feeder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return {"session_id": session_id, **feeder.status.to_dict()}


@router.post("/api/drip-feed/cancel/{session_id}")
async def api_drip_feed_cancel(session_id: int):
    """Cancel an active drip feed session."""
    feeder = _drip_sessions.get(session_id) or _tcp_sessions.get(session_id)
    if not feeder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    feeder.cancel()
    return {"session_id": session_id, "state": "cancelling"}


@router.post("/api/generate")
async def api_generate_gcode(request: Request):
    """Generate probing G-code from cycle parameters."""
    body = await request.json()

    cycle = body.get("cycle", "")
    mode = body.get("mode", "manual")  # "renishaw" or "manual"
    params = body.get("params", {})

    if not cycle:
        return JSONResponse({"error": "Cycle type required"}, status_code=400)

    try:
        gcode = generate_probe_gcode(cycle, mode, params)
        return {"gcode": gcode, "cycle": cycle, "mode": mode}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# --- G-code Generation ---

def generate_probe_gcode(cycle: str, mode: str, params: dict) -> str:
    """Generate probing G-code for the given cycle and mode.

    Args:
        cycle: Cycle type (single_surface, bore, boss, corner, pocket, web)
        mode: "renishaw" (G65 Pxxxx macros) or "manual" (G31 skip function)
        params: Cycle parameters (axis, direction, wcs, feed, etc.)
    """
    wcs = params.get("wcs", "G54")
    feed = params.get("feed", 100)
    tool = params.get("tool", 99)
    clearance = params.get("clearance", 5.0)
    set_wcs = params.get("set_wcs", True)

    generators = {
        "single_surface": _gen_single_surface,
        "bore": _gen_bore,
        "boss": _gen_boss,
        "corner": _gen_corner,
        "pocket_width": _gen_pocket_width,
        "outside_box": _gen_outside_box,
    }

    gen = generators.get(cycle)
    if gen is None:
        raise ValueError(f"Unknown cycle: {cycle}")

    return gen(mode, params, wcs, feed, tool, clearance, set_wcs)


def _header(tool: int, comment: str) -> str:
    return f"""%
O9900 ({comment})
(Generated by CNC Network Manager)
(Probe Tool: T{tool})
G21 G90 G40 G49 G80
T{tool} M06
G43 H{tool}
"""


def _set_wcs_gcode(wcs: str, axis: str, value_expr: str) -> str:
    """Generate G10 L2 to set a work offset."""
    # G54=P1, G55=P2, ... G59=P6
    wcs_map = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}
    p_num = wcs_map.get(wcs.upper(), 1)
    return f"G10 L2 P{p_num} {axis.upper()}{value_expr}"


def _footer() -> str:
    return """G91 G28 Z0
M30
%"""


# --- Single Surface ---

def _gen_single_surface(mode: str, params: dict, wcs: str, feed: int,
                         tool: int, clearance: float, set_wcs: bool) -> str:
    axis = params.get("axis", "Z").upper()
    direction = params.get("direction", "-")  # "+" or "-"
    approach = float(params.get("approach_pos", 0))
    expected = float(params.get("expected_pos", 0))

    lines = [_header(tool, f"Single Surface Probe - {axis}{direction}")]

    if mode == "renishaw":
        # Renishaw macro G65 P9811
        # S = work offset number (1=G54 ... 6=G59)
        wcs_num = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}.get(wcs, 1)
        move_axis = {"X": "X", "Y": "Y", "Z": "Z"}.get(axis, "Z")

        lines.append(f"(Move to approach position)")
        lines.append(f"G00 {move_axis}{approach}")
        lines.append(f"(Renishaw single surface probe)")
        lines.append(f"G65 P9811 {move_axis}{expected} S{wcs_num if set_wcs else 0} F{feed}")
        lines.append(f"(Probe result stored in #5061-#5063)")
        if set_wcs:
            lines.append(f"({wcs} {axis} set to probed value)")

    else:
        # Manual probing with G31
        sign = -1 if direction == "-" else 1
        probe_target = expected - (sign * 50)  # Overshoot target

        lines.append(f"(Move to approach position)")
        lines.append(f"G00 {axis}{approach}")
        lines.append(f"(Probe move - G31 skip)")
        lines.append(f"G31 {axis}{probe_target} F{feed}")
        lines.append(f"(Read probed position from skip signal)")

        # Store probed position
        probe_var = {"X": "#5061", "Y": "#5062", "Z": "#5063"}.get(axis, "#5061")
        lines.append(f"#{100} = {probe_var}")
        lines.append(f"(Probed {axis} = #{100})")

        # Retract
        lines.append(f"G00 {axis}{approach}")

        if set_wcs:
            lines.append(f"(Set {wcs} {axis} to probed position)")
            lines.append(_set_wcs_gcode(wcs, axis, f"#{100}"))

    lines.append("")
    lines.append(_footer())
    return "\n".join(lines)


# --- Bore ---

def _gen_bore(mode: str, params: dict, wcs: str, feed: int,
              tool: int, clearance: float, set_wcs: bool) -> str:
    diameter = float(params.get("diameter", 50))
    depth = float(params.get("depth", -10))

    lines = [_header(tool, f"Bore Center Probe - D{diameter}")]

    if mode == "renishaw":
        wcs_num = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}.get(wcs, 1)
        lines.append(f"(Position probe above bore center)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"(Move to probing depth)")
        lines.append(f"G00 Z{depth}")
        lines.append(f"(Renishaw bore probe)")
        lines.append(f"G65 P9812 D{diameter} S{wcs_num if set_wcs else 0} F{feed}")
        if set_wcs:
            lines.append(f"({wcs} X/Y set to bore center)")
    else:
        half_d = diameter / 2
        safe = half_d - 5 if half_d > 5 else half_d * 0.5
        lines.append(f"(Manual bore probing - 4 touch)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"G00 Z{depth}")
        lines.append(f"")
        lines.append(f"(Probe X+)")
        lines.append(f"G00 X-{safe:.1f}")
        lines.append(f"G31 X{half_d + 10:.1f} F{feed}")
        lines.append(f"#101 = #5061")
        lines.append(f"G00 X-{safe:.1f}")
        lines.append(f"")
        lines.append(f"(Probe X-)")
        lines.append(f"G00 X{safe:.1f}")
        lines.append(f"G31 X-{half_d + 10:.1f} F{feed}")
        lines.append(f"#102 = #5061")
        lines.append(f"G00 X{safe:.1f}")
        lines.append(f"")
        lines.append(f"(Probe Y+)")
        lines.append(f"G00 X0 Y-{safe:.1f}")
        lines.append(f"G31 Y{half_d + 10:.1f} F{feed}")
        lines.append(f"#103 = #5062")
        lines.append(f"G00 Y-{safe:.1f}")
        lines.append(f"")
        lines.append(f"(Probe Y-)")
        lines.append(f"G00 Y{safe:.1f}")
        lines.append(f"G31 Y-{half_d + 10:.1f} F{feed}")
        lines.append(f"#104 = #5062")
        lines.append(f"G00 Y0")
        lines.append(f"")
        lines.append(f"(Calculate center)")
        lines.append(f"#110 = [#101 + #102] / 2 (X center)")
        lines.append(f"#111 = [#103 + #104] / 2 (Y center)")
        if set_wcs:
            lines.append(f"(Set {wcs} X/Y to bore center)")
            lines.append(_set_wcs_gcode(wcs, "X", "#110"))
            lines.append(_set_wcs_gcode(wcs, "Y", "#111"))

    lines.append(f"")
    lines.append(f"G00 Z{clearance}")
    lines.append(_footer())
    return "\n".join(lines)


# --- Boss ---

def _gen_boss(mode: str, params: dict, wcs: str, feed: int,
              tool: int, clearance: float, set_wcs: bool) -> str:
    diameter = float(params.get("diameter", 50))

    lines = [_header(tool, f"Boss Center Probe - D{diameter}")]

    if mode == "renishaw":
        wcs_num = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}.get(wcs, 1)
        lines.append(f"(Position probe above boss center)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"(Renishaw boss probe)")
        lines.append(f"G65 P9814 D{diameter} S{wcs_num if set_wcs else 0} F{feed}")
        if set_wcs:
            lines.append(f"({wcs} X/Y set to boss center)")
    else:
        half_d = diameter / 2
        overshoot = half_d + 20
        probe_z = float(params.get("probe_z", -5))
        lines.append(f"(Manual boss probing - 4 touch)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Probe X+ side)")
        lines.append(f"G00 X-{overshoot:.1f} Y0")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 X0 F{feed}")
        lines.append(f"#101 = #5061")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Probe X- side)")
        lines.append(f"G00 X{overshoot:.1f}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 X0 F{feed}")
        lines.append(f"#102 = #5061")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Probe Y+ side)")
        lines.append(f"G00 X0 Y-{overshoot:.1f}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 Y0 F{feed}")
        lines.append(f"#103 = #5062")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Probe Y- side)")
        lines.append(f"G00 Y{overshoot:.1f}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 Y0 F{feed}")
        lines.append(f"#104 = #5062")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Calculate center)")
        lines.append(f"#110 = [#101 + #102] / 2")
        lines.append(f"#111 = [#103 + #104] / 2")
        if set_wcs:
            lines.append(_set_wcs_gcode(wcs, "X", "#110"))
            lines.append(_set_wcs_gcode(wcs, "Y", "#111"))

    lines.append("")
    lines.append(_footer())
    return "\n".join(lines)


# --- Corner ---

def _gen_corner(mode: str, params: dict, wcs: str, feed: int,
                tool: int, clearance: float, set_wcs: bool) -> str:
    corner = params.get("corner", "XY+")  # which corner: XY++, XY+-, XY-+, XY--
    probe_z = float(params.get("probe_z", -5))
    distance = float(params.get("distance", 20))

    lines = [_header(tool, f"Corner Probe - {corner}")]

    if mode == "renishaw":
        wcs_num = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}.get(wcs, 1)
        lines.append(f"(Position probe near corner)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"(Renishaw corner probe)")
        lines.append(f"G65 P9811 X{distance} S{wcs_num if set_wcs else 0} F{feed}")
        lines.append(f"G65 P9811 Y{distance} S{wcs_num if set_wcs else 0} F{feed}")
        if set_wcs:
            lines.append(f"({wcs} X/Y set to corner)")
    else:
        x_dir = 1 if "X+" in corner or corner.endswith("++") or corner.endswith("-+") else -1
        y_dir = 1 if "Y+" in corner or corner.endswith("++") or corner.endswith("+-") else -1

        lines.append(f"(Manual corner probing)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"")
        lines.append(f"(Probe X surface)")
        lines.append(f"G00 X{-x_dir * distance:.1f}")
        lines.append(f"G31 X{x_dir * distance:.1f} F{feed}")
        lines.append(f"#101 = #5061 (X surface)")
        lines.append(f"G00 X{-x_dir * distance:.1f}")
        lines.append(f"")
        lines.append(f"(Probe Y surface)")
        lines.append(f"G00 Y{-y_dir * distance:.1f}")
        lines.append(f"G31 Y{y_dir * distance:.1f} F{feed}")
        lines.append(f"#102 = #5062 (Y surface)")
        lines.append(f"G00 Y{-y_dir * distance:.1f}")
        lines.append(f"")
        if set_wcs:
            lines.append(f"(Set {wcs} to corner)")
            lines.append(_set_wcs_gcode(wcs, "X", "#101"))
            lines.append(_set_wcs_gcode(wcs, "Y", "#102"))

    lines.append(f"G00 Z{clearance}")
    lines.append("")
    lines.append(_footer())
    return "\n".join(lines)


# --- Pocket Width ---

def _gen_pocket_width(mode: str, params: dict, wcs: str, feed: int,
                      tool: int, clearance: float, set_wcs: bool) -> str:
    axis = params.get("axis", "X").upper()
    width = float(params.get("width", 50))
    depth = float(params.get("depth", -10))

    lines = [_header(tool, f"Pocket Width Probe - {axis} W{width}")]

    if mode == "renishaw":
        wcs_num = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}.get(wcs, 1)
        lines.append(f"(Position probe inside pocket)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"G00 Z{depth}")
        lines.append(f"(Renishaw web/pocket probe)")
        lines.append(f"G65 P9812 {axis}{width} S{wcs_num if set_wcs else 0} F{feed}")
    else:
        half_w = width / 2
        safe = half_w - 5 if half_w > 5 else half_w * 0.5
        var1 = "#5061" if axis == "X" else "#5062"

        lines.append(f"(Manual pocket width - {axis} axis)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"G00 Z{depth}")
        lines.append(f"")
        lines.append(f"(Probe {axis}+ wall)")
        lines.append(f"G00 {axis}-{safe:.1f}")
        lines.append(f"G31 {axis}{half_w + 10:.1f} F{feed}")
        lines.append(f"#101 = {var1}")
        lines.append(f"G00 {axis}-{safe:.1f}")
        lines.append(f"")
        lines.append(f"(Probe {axis}- wall)")
        lines.append(f"G00 {axis}{safe:.1f}")
        lines.append(f"G31 {axis}-{half_w + 10:.1f} F{feed}")
        lines.append(f"#102 = {var1}")
        lines.append(f"G00 {axis}0")
        lines.append(f"")
        lines.append(f"(Calculate center)")
        lines.append(f"#110 = [#101 + #102] / 2")
        lines.append(f"(Measured width = ABS[#101 - #102])")
        if set_wcs:
            lines.append(f"(Set {wcs} {axis} to pocket center)")
            lines.append(_set_wcs_gcode(wcs, axis, "#110"))

    lines.append(f"")
    lines.append(f"G00 Z{clearance}")
    lines.append("")
    lines.append(_footer())
    return "\n".join(lines)


# --- Outside Box (Stock Setup) ---

def _gen_outside_box(mode: str, params: dict, wcs: str, feed: int,
                     tool: int, clearance: float, set_wcs: bool) -> str:
    """Probe outside of rectangular stock to find X/Y center and Z top.

    The operator positions the probe approximately above the center of the stock.
    The cycle:
    1. Probes Z top surface
    2. Moves down to probe_z, probes X+ then X- (finds X center)
    3. Probes Y+ then Y- (finds Y center)
    4. Returns to center at clearance height
    5. Sets WCS X/Y to stock center, Z to top surface
    """
    x_width = float(params.get("x_width", 100))
    y_width = float(params.get("y_width", 100))
    z_start = float(params.get("z_start", 10))       # Height above stock to start
    probe_z = float(params.get("probe_z", -10))       # Z depth for X/Y probing
    safety = float(params.get("safety", 20))           # Extra clearance beyond stock edge
    probe_top = params.get("probe_top", True)          # Probe Z top surface

    half_x = x_width / 2
    half_y = y_width / 2
    overshoot_x = half_x + safety
    overshoot_y = half_y + safety

    lines = [_header(tool, f"Outside Box - Stock Setup {x_width}x{y_width}")]
    lines.append(f"(Stock size: X={x_width} Y={y_width})")
    lines.append(f"(Safety clearance: {safety}mm beyond stock edge)")
    lines.append(f"(Position probe near center of stock before running)")
    lines.append(f"")

    if mode == "renishaw":
        wcs_num = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}.get(wcs, 1)

        if probe_top:
            lines.append(f"(=== Step 1: Probe Z top surface ===)")
            lines.append(f"G00 Z{z_start}")
            lines.append(f"G65 P9811 Z0. S{wcs_num if set_wcs else 0} F{feed}")
            lines.append(f"G00 Z{clearance}")
            lines.append(f"")

        lines.append(f"(=== Step 2: Probe X width (find center) ===)")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G65 P9812 X{x_width} S{wcs_num if set_wcs else 0} F{feed}")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")

        lines.append(f"(=== Step 3: Probe Y width (find center) ===)")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G65 P9812 Y{y_width} S{wcs_num if set_wcs else 0} F{feed}")
        lines.append(f"G00 Z{clearance}")

        if set_wcs:
            lines.append(f"({wcs} X/Y/Z set to stock center and top)")

    else:
        # Manual mode — full sequence with G31

        if probe_top:
            lines.append(f"(=== Step 1: Probe Z top surface ===)")
            lines.append(f"G00 Z{z_start}")
            lines.append(f"G31 Z-{z_start + 20:.1f} F{feed}")
            lines.append(f"#100 = #5063 (Z top surface)")
            lines.append(f"G00 Z{z_start}")
            lines.append(f"")

        lines.append(f"(=== Step 2: Probe X sides ===)")
        lines.append(f"(Move to X+ side)")
        lines.append(f"G00 X{overshoot_x:.1f}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 X-{overshoot_x:.1f} F{feed}")
        lines.append(f"#101 = #5061 (X+ surface)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Move to X- side)")
        lines.append(f"G00 X-{overshoot_x:.1f}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 X{overshoot_x:.1f} F{feed}")
        lines.append(f"#102 = #5061 (X- surface)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(X center)")
        lines.append(f"#110 = [#101 + #102] / 2")
        lines.append(f"(X measured width = ABS[#101 - #102])")
        lines.append(f"")

        lines.append(f"(=== Step 3: Probe Y sides ===)")
        lines.append(f"(Move to center X, then Y+ side)")
        lines.append(f"G00 X#110")
        lines.append(f"G00 Y{overshoot_y:.1f}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 Y-{overshoot_y:.1f} F{feed}")
        lines.append(f"#103 = #5062 (Y+ surface)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Move to Y- side)")
        lines.append(f"G00 Y-{overshoot_y:.1f}")
        lines.append(f"G00 Z{probe_z}")
        lines.append(f"G31 Y{overshoot_y:.1f} F{feed}")
        lines.append(f"#104 = #5062 (Y- surface)")
        lines.append(f"G00 Z{clearance}")
        lines.append(f"")
        lines.append(f"(Y center)")
        lines.append(f"#111 = [#103 + #104] / 2")
        lines.append(f"(Y measured width = ABS[#103 - #104])")
        lines.append(f"")

        lines.append(f"(=== Results ===)")
        lines.append(f"(X center = #110)")
        lines.append(f"(Y center = #111)")
        if probe_top:
            lines.append(f"(Z top    = #100)")

        if set_wcs:
            lines.append(f"")
            lines.append(f"(=== Set {wcs} to stock center/top ===)")
            lines.append(_set_wcs_gcode(wcs, "X", "#110"))
            lines.append(_set_wcs_gcode(wcs, "Y", "#111"))
            if probe_top:
                lines.append(_set_wcs_gcode(wcs, "Z", "#100"))

        # Return to center
        lines.append(f"")
        lines.append(f"(Return to center)")
        lines.append(f"G00 X#110 Y#111")

    lines.append(f"G00 Z{clearance}")
    lines.append("")
    lines.append(_footer())
    return "\n".join(lines)
