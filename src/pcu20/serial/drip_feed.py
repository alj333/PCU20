"""RS-232 drip feed for sending G-code to CNC machines line-by-line.

Supports Fanuc protocol: XON/XOFF flow control, DC2/DC4 framing,
configurable baud rate and serial parameters.

Fanuc RS-232 protocol:
- CNC sends DC1 (XON, 0x11) when ready to receive
- CNC sends DC3 (XOFF, 0x13) when buffer is full
- Program starts with % and ends with %
- Some machines use DC2 (0x12) to request start and DC4 (0x14) to end
"""

from __future__ import annotations

import asyncio
import platform
import time
from dataclasses import dataclass, field
from enum import Enum

import structlog

log = structlog.get_logger()

# Control characters
XON = b"\x11"   # DC1 — resume transmission
XOFF = b"\x13"  # DC3 — pause transmission
DC2 = b"\x12"   # Start of program request
DC4 = b"\x14"   # End of program


class DripFeedState(str, Enum):
    IDLE = "idle"
    WAITING = "waiting"       # Waiting for CNC to request data (DC2/XON)
    SENDING = "sending"       # Actively sending lines
    PAUSED = "paused"         # Paused by XOFF from CNC
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class DripFeedStatus:
    """Current status of a drip feed session."""
    state: DripFeedState = DripFeedState.IDLE
    total_lines: int = 0
    lines_sent: int = 0
    bytes_sent: int = 0
    start_time: float | None = None
    error: str = ""

    @property
    def progress(self) -> float:
        if self.total_lines == 0:
            return 0
        return self.lines_sent / self.total_lines * 100

    @property
    def elapsed(self) -> float:
        if self.start_time is None:
            return 0
        return time.time() - self.start_time

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "total_lines": self.total_lines,
            "lines_sent": self.lines_sent,
            "bytes_sent": self.bytes_sent,
            "progress": round(self.progress, 1),
            "elapsed": round(self.elapsed, 1),
            "error": self.error,
        }


class DripFeeder:
    """RS-232 drip feed sender for Fanuc CNC machines."""

    def __init__(
        self,
        port: str,
        baud_rate: int = 9600,
        data_bits: int = 8,
        parity: str = "none",
        stop_bits: int = 2,
        flow_control: str = "xon_xoff",
        line_delay_ms: int = 0,
    ) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.data_bits = data_bits
        self.parity = parity
        self.stop_bits = stop_bits
        self.flow_control = flow_control
        self.line_delay_ms = line_delay_ms
        self._serial = None
        self._cancel = False
        self.status = DripFeedStatus()

    def _open(self) -> None:
        """Open the serial port."""
        import serial

        parity_map = {
            "none": serial.PARITY_NONE,
            "even": serial.PARITY_EVEN,
            "odd": serial.PARITY_ODD,
        }
        stopbits_map = {
            1: serial.STOPBITS_ONE,
            2: serial.STOPBITS_TWO,
        }

        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baud_rate,
            bytesize=self.data_bits,
            parity=parity_map.get(self.parity, serial.PARITY_NONE),
            stopbits=stopbits_map.get(self.stop_bits, serial.STOPBITS_TWO),
            xonxoff=(self.flow_control == "xon_xoff"),
            rtscts=(self.flow_control == "rts_cts"),
            timeout=1,
            write_timeout=10,
        )
        log.info("serial.opened", port=self.port, baud=self.baud_rate)

    def _close(self) -> None:
        """Close the serial port."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            log.info("serial.closed", port=self.port)

    def send_sync(self, gcode: str) -> None:
        """Send G-code via drip feed (blocking — run in thread).

        This implements the Fanuc RS-232 drip feed protocol:
        1. Open port
        2. Wait for XON/DC2 from CNC (machine is in EDIT or DNC mode)
        3. Send program line by line, respecting XON/XOFF flow control
        4. Close port
        """
        lines = gcode.strip().splitlines()
        self.status = DripFeedStatus(
            state=DripFeedState.WAITING,
            total_lines=len(lines),
        )
        self._cancel = False

        try:
            self._open()
            self.status.state = DripFeedState.WAITING
            self.status.start_time = time.time()

            log.info("serial.waiting_for_cnc", port=self.port)

            # Wait for CNC to signal ready (XON or DC2)
            # Some machines send DC2 when operator presses READ/INPUT
            # Others just accept data immediately
            # We wait up to 60 seconds, then start anyway
            ready = self._wait_for_ready(timeout=60)
            if not ready:
                log.info("serial.no_ready_signal", msg="Starting send anyway")

            if self._cancel:
                self.status.state = DripFeedState.CANCELLED
                return

            # Send lines
            self.status.state = DripFeedState.SENDING
            log.info("serial.sending", lines=len(lines))

            for i, line in enumerate(lines):
                if self._cancel:
                    self.status.state = DripFeedState.CANCELLED
                    return

                # Check for XOFF (pause)
                self._check_flow_control()

                # Send line with CR/LF (Fanuc expects \r\n or \n)
                line_data = line.rstrip() + "\r\n"
                self._serial.write(line_data.encode("ascii", errors="replace"))
                self._serial.flush()

                self.status.lines_sent = i + 1
                self.status.bytes_sent += len(line_data)

                # Optional inter-line delay for slower machines
                if self.line_delay_ms > 0:
                    time.sleep(self.line_delay_ms / 1000)

            self.status.state = DripFeedState.COMPLETED
            log.info("serial.completed",
                      lines=self.status.lines_sent,
                      bytes=self.status.bytes_sent,
                      elapsed=f"{self.status.elapsed:.1f}s")

        except Exception as e:
            self.status.state = DripFeedState.ERROR
            self.status.error = str(e)
            log.error("serial.error", error=str(e))
        finally:
            self._close()

    def cancel(self) -> None:
        """Cancel an active drip feed."""
        self._cancel = True

    def _wait_for_ready(self, timeout: float = 60) -> bool:
        """Wait for XON or DC2 from the CNC."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._cancel:
                return False
            if self._serial.in_waiting > 0:
                data = self._serial.read(self._serial.in_waiting)
                if XON in data or DC2 in data:
                    log.info("serial.cnc_ready")
                    return True
            time.sleep(0.1)
        return False

    def _check_flow_control(self) -> None:
        """Handle XON/XOFF flow control from CNC."""
        if not self._serial or self.flow_control != "xon_xoff":
            return

        # pyserial handles XON/XOFF automatically when xonxoff=True,
        # but we also check manually for explicit pause/resume
        while self._serial.in_waiting > 0:
            byte = self._serial.read(1)
            if byte == XOFF:
                self.status.state = DripFeedState.PAUSED
                log.info("serial.paused_by_cnc")
                # Wait for XON to resume
                while not self._cancel:
                    if self._serial.in_waiting > 0:
                        resume = self._serial.read(1)
                        if resume == XON:
                            self.status.state = DripFeedState.SENDING
                            log.info("serial.resumed_by_cnc")
                            return
                    time.sleep(0.01)


def list_serial_ports() -> list[dict]:
    """List available serial ports on this system."""
    try:
        from serial.tools.list_ports import comports
        ports = []
        for port in comports():
            ports.append({
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
            })
        return ports
    except ImportError:
        return []
