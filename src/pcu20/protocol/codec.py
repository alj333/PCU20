"""Wire format codec — frame extraction and serialization.

The exact framing format is TBD until real protocol captures are analyzed.
This implementation assumes a common industrial pattern:
  [4-byte LE length] [1-byte command ID] [payload...]

The codec is designed to be easily swapped once the real format is known.
"""

from __future__ import annotations

import struct

import structlog

from pcu20.protocol.types import (
    BYTE_ORDER,
    FRAME_HEADER_SIZE,
    MAX_FRAME_SIZE,
    Frame,
)

log = structlog.get_logger()


class FrameCodec:
    """Handles framing: extracting complete messages from a TCP byte stream."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        """Feed raw bytes from the socket, return list of complete frames."""
        self._buffer.extend(data)
        frames: list[Frame] = []
        while (frame := self._try_extract_frame()) is not None:
            frames.append(frame)
        return frames

    def _try_extract_frame(self) -> Frame | None:
        """Try to extract one complete frame from the buffer.

        Expected wire format (provisional):
            [uint32 LE: total payload length] [uint8: command_id] [payload bytes...]

        Returns None if the buffer doesn't contain a complete frame yet.
        """
        if len(self._buffer) < FRAME_HEADER_SIZE:
            return None

        # Read length prefix
        length = int.from_bytes(self._buffer[:FRAME_HEADER_SIZE], BYTE_ORDER)

        if length > MAX_FRAME_SIZE or length == 0:
            log.error("codec.invalid_frame_length", length=length, max=MAX_FRAME_SIZE)
            # Skip this 4-byte header and try to resync from the next byte
            del self._buffer[:1]
            return self._try_extract_frame() if len(self._buffer) >= FRAME_HEADER_SIZE else None

        total_size = FRAME_HEADER_SIZE + length
        if len(self._buffer) < total_size:
            return None  # Incomplete frame, wait for more data

        # Extract the frame
        raw = bytes(self._buffer[:total_size])
        frame_data = bytes(self._buffer[FRAME_HEADER_SIZE:total_size])
        del self._buffer[:total_size]

        if len(frame_data) < 1:
            log.warning("codec.empty_frame")
            return None

        command_id = frame_data[0]
        payload = frame_data[1:]

        return Frame(command_id=command_id, payload=payload, raw=raw)

    def reset(self) -> None:
        """Clear the internal buffer (e.g., on reconnect)."""
        self._buffer.clear()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)


def encode_response(command_id: int, status: int, payload: bytes = b"") -> bytes:
    """Encode a response frame to send back to the CNC.

    Wire format (provisional):
        [uint32 LE: length] [uint8: command_id] [uint8: status] [payload...]
    """
    body = struct.pack("BB", command_id, status) + payload
    header = len(body).to_bytes(FRAME_HEADER_SIZE, BYTE_ORDER)
    return header + body
