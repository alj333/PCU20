"""TCP/LAN-based drip feed for network drip feed units.

Many shop floor drip feed units (e.g., Predator DNC, WinDNC, custom units)
act as a TCP server that accepts G-code over a socket and feeds it to the
CNC via RS-232. This module connects to such units over the LAN.

Protocol: Plain TCP — send G-code as ASCII text. The drip feed unit handles
the RS-232 timing and flow control to the CNC.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from pcu20.serial.drip_feed import DripFeedState, DripFeedStatus

log = structlog.get_logger()


class TCPDripFeeder:
    """TCP drip feed sender for LAN-based drip feed units."""

    def __init__(
        self,
        host: str,
        port: int = 9100,
        timeout: int = 10,
        line_delay_ms: int = 0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.line_delay_ms = line_delay_ms
        self._cancel = False
        self.status = DripFeedStatus()

    async def send(self, gcode: str) -> None:
        """Send G-code to a LAN drip feed unit."""
        lines = gcode.strip().splitlines()
        self.status = DripFeedStatus(
            state=DripFeedState.WAITING,
            total_lines=len(lines),
            start_time=time.time(),
        )
        self._cancel = False

        try:
            log.info("tcp_drip.connecting", host=self.host, port=self.port)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )

            self.status.state = DripFeedState.SENDING
            log.info("tcp_drip.sending", lines=len(lines))

            for i, line in enumerate(lines):
                if self._cancel:
                    self.status.state = DripFeedState.CANCELLED
                    break

                line_data = line.rstrip() + "\r\n"
                writer.write(line_data.encode("ascii", errors="replace"))
                await writer.drain()

                self.status.lines_sent = i + 1
                self.status.bytes_sent += len(line_data)

                if self.line_delay_ms > 0:
                    await asyncio.sleep(self.line_delay_ms / 1000)

            if self.status.state == DripFeedState.SENDING:
                self.status.state = DripFeedState.COMPLETED

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            log.info("tcp_drip.completed",
                      lines=self.status.lines_sent,
                      bytes=self.status.bytes_sent,
                      elapsed=f"{self.status.elapsed:.1f}s")

        except asyncio.TimeoutError:
            self.status.state = DripFeedState.ERROR
            self.status.error = f"Connection timed out ({self.timeout}s)"
            log.error("tcp_drip.timeout", host=self.host)
        except ConnectionRefusedError:
            self.status.state = DripFeedState.ERROR
            self.status.error = "Connection refused — check IP/port"
            log.error("tcp_drip.refused", host=self.host, port=self.port)
        except Exception as e:
            self.status.state = DripFeedState.ERROR
            self.status.error = str(e)
            log.error("tcp_drip.error", error=str(e))

    def cancel(self) -> None:
        self._cancel = True
