"""Replay captured PCU20 protocol sessions for testing.

Reads capture files produced by capture_proxy.py and replays the client side
against a running server, comparing responses to the original.

Usage:
    python tools/replay.py capture.bin --host localhost --port 6743
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
from pathlib import Path

HEADER_MAGIC = b"PCU20CAP"


def read_capture_file(path: Path) -> list[dict]:
    """Read all records from a capture file."""
    records = []
    with open(path, "rb") as f:
        # Read header
        magic = f.read(8)
        if magic != HEADER_MAGIC:
            print(f"Error: not a PCU20 capture file (got {magic!r})")
            sys.exit(1)

        version = struct.unpack("<I", f.read(4))[0]
        start_ts = struct.unpack("<d", f.read(8))[0]
        print(f"Capture file v{version}, started at {start_ts}")

        # Read records
        while True:
            rec_header = f.read(2 + 1 + 8 + 4)  # session_id + direction + timestamp + length
            if len(rec_header) < 15:
                break

            session_id, direction, timestamp, length = struct.unpack("<HBdI", rec_header)
            data = f.read(length)
            if len(data) < length:
                break

            records.append({
                "session_id": session_id,
                "direction": chr(direction),  # 'C' or 'S'
                "timestamp": timestamp,
                "data": data,
            })

    print(f"Read {len(records)} records")
    return records


async def replay_session(
    records: list[dict],
    session_id: int,
    host: str,
    port: int,
) -> None:
    """Replay one captured session against a server."""
    session_records = [r for r in records if r["session_id"] == session_id]
    if not session_records:
        print(f"No records for session {session_id}")
        return

    print(f"\nReplaying session {session_id} ({len(session_records)} records)...")
    reader, writer = await asyncio.open_connection(host, port)

    mismatches = 0
    for rec in session_records:
        if rec["direction"] == "C":
            # Client->Server: send this data
            writer.write(rec["data"])
            await writer.drain()
            print(f"  SENT {len(rec['data'])} bytes")
        else:
            # Server->Client: read and compare
            try:
                response = await asyncio.wait_for(reader.read(65536), timeout=5.0)
                if response == rec["data"]:
                    print(f"  RECV {len(response)} bytes -- MATCH")
                else:
                    print(f"  RECV {len(response)} bytes -- MISMATCH")
                    print(f"    Expected: {rec['data'][:64].hex(' ')}")
                    print(f"    Got:      {response[:64].hex(' ')}")
                    mismatches += 1
            except asyncio.TimeoutError:
                print(f"  RECV TIMEOUT (expected {len(rec['data'])} bytes)")
                mismatches += 1

    writer.close()
    await writer.wait_closed()

    if mismatches == 0:
        print(f"Session {session_id}: ALL MATCHED")
    else:
        print(f"Session {session_id}: {mismatches} MISMATCHES")


async def main(capture_file: str, host: str, port: int) -> None:
    records = read_capture_file(Path(capture_file))

    # Find unique sessions
    session_ids = sorted(set(r["session_id"] for r in records))
    print(f"Found {len(session_ids)} sessions: {session_ids}")

    for sid in session_ids:
        await replay_session(records, sid, host, port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay PCU20 captured sessions")
    parser.add_argument("capture_file", help="Path to capture file (.bin)")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=6743, help="Server port")
    args = parser.parse_args()

    asyncio.run(main(args.capture_file, args.host, args.port))
