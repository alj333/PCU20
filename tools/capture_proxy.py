"""MITM capture proxy for PCU20 protocol reverse-engineering.

Sits between a real PCU20 CNC controller and the original PCU20 Network Manager
software, capturing and logging all bytes exchanged in both directions.

Usage:
    python -m pcu20 capture --target-host 192.168.1.100 --target-port 6743

Setup:
    1. Run original PCU20 Network Manager on a different port (e.g., 16743)
    2. Run this proxy on port 6743 pointing to the original on 16743
    3. Configure the CNC to connect to this machine's IP on port 6743
    4. All traffic is captured to a binary log file for analysis
"""

from __future__ import annotations

import asyncio
import struct
import time
from pathlib import Path

HEADER = b"PCU20CAP"  # Magic header for capture files
VERSION = 1


async def run_capture_proxy(
    target_host: str,
    target_port: int,
    listen_port: int,
    output_file: str,
) -> None:
    """Run the MITM capture proxy."""
    output_path = Path(output_file)
    print(f"PCU20 Capture Proxy")
    print(f"  Listening on    : 0.0.0.0:{listen_port}")
    print(f"  Forwarding to   : {target_host}:{target_port}")
    print(f"  Capture file    : {output_path}")
    print()

    capture_handle = open(output_path, "wb")
    # Write capture file header
    capture_handle.write(HEADER)
    capture_handle.write(struct.pack("<I", VERSION))
    capture_handle.write(struct.pack("<d", time.time()))  # start timestamp

    session_counter = 0

    async def handle_connection(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        nonlocal session_counter
        session_id = session_counter
        session_counter += 1

        peer = client_writer.get_extra_info("peername")
        print(f"[{session_id}] Connection from {peer[0]}:{peer[1]}")

        # Connect to the real server
        try:
            server_reader, server_writer = await asyncio.open_connection(
                target_host, target_port
            )
        except OSError as e:
            print(f"[{session_id}] Cannot connect to target: {e}")
            client_writer.close()
            return

        print(f"[{session_id}] Connected to target {target_host}:{target_port}")

        def write_capture_record(direction: bytes, data: bytes) -> None:
            """Write a capture record: [session_id:u16][direction:1][timestamp:f64][length:u32][data]"""
            record = struct.pack(
                "<HBdI",
                session_id,
                direction[0],  # b'C' or b'S'
                time.time(),
                len(data),
            )
            capture_handle.write(record)
            capture_handle.write(data)
            capture_handle.flush()

        async def forward(
            src_reader: asyncio.StreamReader,
            dst_writer: asyncio.StreamWriter,
            direction: bytes,
            label: str,
        ) -> None:
            try:
                while True:
                    data = await src_reader.read(65536)
                    if not data:
                        break

                    write_capture_record(direction, data)
                    _print_hex_summary(session_id, label, data)

                    dst_writer.write(data)
                    await dst_writer.drain()
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                dst_writer.close()

        # Forward in both directions concurrently
        try:
            await asyncio.gather(
                forward(client_reader, server_writer, b"C", "CNC->SRV"),
                forward(server_reader, client_writer, b"S", "SRV->CNC"),
            )
        except Exception as e:
            print(f"[{session_id}] Error: {e}")
        finally:
            print(f"[{session_id}] Session closed")
            for w in (client_writer, server_writer):
                try:
                    w.close()
                except Exception:
                    pass

    server = await asyncio.start_server(
        handle_connection, "0.0.0.0", listen_port
    )

    print("Proxy running. Press Ctrl+C to stop.\n")

    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        capture_handle.close()
        print(f"\nCapture saved to {output_path}")


def _print_hex_summary(session_id: int, label: str, data: bytes) -> None:
    """Print a brief hex summary of captured data."""
    hex_preview = data[:64].hex(" ")
    suffix = "..." if len(data) > 64 else ""
    print(f"  [{session_id}] {label} ({len(data):>5} bytes): {hex_preview}{suffix}")
