"""Protocol discovery — logs unknown commands and raw data for reverse-engineering."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pcu20.protocol.session import Session

log = structlog.get_logger()


class ProtocolDiscovery:
    """Logs raw protocol data and unknown commands for analysis."""

    def __init__(self, trace_file: str | None = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self._trace_file = Path(trace_file) if trace_file else None
        self._trace_handle = None

    def start(self) -> None:
        if self._trace_file and self.enabled:
            self._trace_handle = open(self._trace_file, "ab")
            log.info("discovery.trace_started", file=str(self._trace_file))

    def stop(self) -> None:
        if self._trace_handle:
            self._trace_handle.close()
            self._trace_handle = None

    def log_raw(self, session_id: str, direction: str, data: bytes) -> None:
        """Log raw bytes exchanged on the wire.

        Args:
            session_id: Unique session identifier.
            direction: "C2S" (client to server) or "S2C" (server to client).
            data: Raw bytes.
        """
        if not self.enabled:
            return

        hex_dump = data.hex(" ")
        log.debug(
            "protocol.raw",
            session=session_id[:8],
            direction=direction,
            length=len(data),
            hex=hex_dump[:200],  # Truncate for console
        )

        if self._trace_handle:
            ts = time.time()
            header = f"\n--- {ts:.6f} {session_id[:8]} {direction} ({len(data)} bytes) ---\n"
            self._trace_handle.write(header.encode())
            self._trace_handle.write(_format_hex_dump(data).encode())
            self._trace_handle.flush()

    def log_unknown_command(self, session_id: str, command_id: int, payload: bytes) -> None:
        """Log an unrecognized command for protocol analysis."""
        log.warning(
            "protocol.unknown_command",
            session=session_id[:8],
            command_id=f"0x{command_id:02X}",
            payload_len=len(payload),
            payload_hex=payload.hex(" ")[:200],
        )

        if self._trace_handle:
            ts = time.time()
            header = f"\n=== {ts:.6f} UNKNOWN CMD 0x{command_id:02X} ({len(payload)} bytes) ===\n"
            self._trace_handle.write(header.encode())
            self._trace_handle.write(_format_hex_dump(payload).encode())
            self._trace_handle.flush()


def _format_hex_dump(data: bytes, width: int = 16) -> str:
    """Format bytes as a traditional hex dump with ASCII sidebar."""
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {offset:08x}  {hex_part:<{width * 3}}  |{ascii_part}|")
    return "\n".join(lines) + "\n"
