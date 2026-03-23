"""Command handler implementations for PCU20 file/directory operations."""

from __future__ import annotations

import asyncio
import os
import shutil
import struct
from typing import TYPE_CHECKING

import structlog

from pcu20.protocol.codec import encode_response
from pcu20.protocol.types import CommandId, DEFAULT_ENCODING, ResponseCode

if TYPE_CHECKING:
    from pcu20.protocol.auth import Authenticator
    from pcu20.protocol.session import Session
    from pcu20.storage.shares import ShareManager
    from pcu20.storage.versioning import VersionManager

log = structlog.get_logger()


def _require_auth(session: Session, command_id: int) -> bytes | None:
    """Return an error response if the session is not authenticated, else None."""
    if not session.is_authenticated:
        return encode_response(command_id, ResponseCode.AUTH_REQUIRED)
    return None


class Handlers:
    """All PCU20 protocol command handlers."""

    def __init__(
        self,
        authenticator: Authenticator,
        share_manager: ShareManager,
        version_manager: VersionManager | None = None,
    ) -> None:
        self.auth = authenticator
        self.shares = share_manager
        self.versions = version_manager

    # --- Authentication ---

    async def handle_login(self, session: Session, payload: bytes) -> bytes:
        """Handle Login command.

        Expected payload (provisional):
            null-terminated username + null-terminated password
        """
        parts = payload.split(b"\x00")
        username = parts[0].decode(DEFAULT_ENCODING)[:256] if len(parts) > 0 else ""
        password = parts[1].decode(DEFAULT_ENCODING)[:256] if len(parts) > 1 else ""

        if self.auth.validate(username, password):
            session.authenticate(username)
            return encode_response(CommandId.LOGIN, ResponseCode.OK)
        else:
            return encode_response(CommandId.LOGIN, ResponseCode.AUTH_FAILED)

    async def handle_terminate(self, session: Session, payload: bytes) -> bytes:
        """Handle TerminateConnect command."""
        session.close_all_handles()
        session.disconnect()
        return encode_response(CommandId.TERMINATE, ResponseCode.OK)

    # --- File Operations ---

    async def handle_read_file(self, session: Session, payload: bytes) -> bytes:
        """Handle ReadFileFromServer — send file content to CNC."""
        if err := _require_auth(session, CommandId.READ_FILE):
            return err

        filepath = payload.rstrip(b"\x00").decode(DEFAULT_ENCODING)
        local_path = self.shares.resolve(filepath, session.username or "")

        if local_path is None or not local_path.is_file():
            return encode_response(CommandId.READ_FILE, ResponseCode.NOT_FOUND)

        try:
            data = await asyncio.to_thread(local_path.read_bytes)
            session.files_transferred += 1
            log.info("handler.read_file", session=session.id[:8], path=filepath, size=len(data))
            size_bytes = struct.pack("<I", len(data))
            return encode_response(CommandId.READ_FILE, ResponseCode.OK, size_bytes + data)
        except OSError as e:
            log.error("handler.read_file_error", path=filepath, error=str(e))
            return encode_response(CommandId.READ_FILE, ResponseCode.ERROR)

    async def handle_write_file(self, session: Session, payload: bytes) -> bytes:
        """Handle WriteFileToServer — receive file content from CNC."""
        if err := _require_auth(session, CommandId.WRITE_FILE):
            return err

        # Expected: null-terminated path + file data
        null_pos = payload.find(b"\x00")
        if null_pos == -1:
            return encode_response(CommandId.WRITE_FILE, ResponseCode.ERROR)

        filepath = payload[:null_pos].decode(DEFAULT_ENCODING)
        file_data = payload[null_pos + 1:]

        local_path = self.shares.resolve(filepath, session.username or "")
        if local_path is None:
            return encode_response(CommandId.WRITE_FILE, ResponseCode.NOT_FOUND)

        share = self.shares.get_share_for_path(filepath)
        if share and share.read_only:
            return encode_response(CommandId.WRITE_FILE, ResponseCode.PERMISSION_DENIED)

        try:
            def _write():
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(file_data)

            await asyncio.to_thread(_write)
            session.files_transferred += 1
            log.info("handler.write_file", session=session.id[:8], path=filepath, size=len(file_data))

            # Trigger versioning
            if self.versions:
                await self.versions.on_file_written(local_path, {
                    "machine_ip": session.peer_ip,
                    "username": session.username or "unknown",
                })

            return encode_response(CommandId.WRITE_FILE, ResponseCode.OK)
        except OSError as e:
            log.error("handler.write_file_error", path=filepath, error=str(e))
            return encode_response(CommandId.WRITE_FILE, ResponseCode.ERROR)

    async def handle_stat_file(self, session: Session, payload: bytes) -> bytes:
        """Handle StatFile — return file metadata."""
        if err := _require_auth(session, CommandId.STAT_FILE):
            return err

        filepath = payload.rstrip(b"\x00").decode(DEFAULT_ENCODING)
        local_path = self.shares.resolve(filepath, session.username or "")

        if local_path is None or not local_path.exists():
            return encode_response(CommandId.STAT_FILE, ResponseCode.NOT_FOUND)

        try:
            stat = await asyncio.to_thread(local_path.stat)
            # Pack: size (uint32), mtime (uint32), is_dir (uint8)
            stat_data = struct.pack(
                "<IIB",
                min(int(stat.st_size), 0xFFFFFFFF),
                int(stat.st_mtime) & 0xFFFFFFFF,
                1 if local_path.is_dir() else 0,
            )
            return encode_response(CommandId.STAT_FILE, ResponseCode.OK, stat_data)
        except OSError as e:
            log.error("handler.stat_error", path=filepath, error=str(e))
            return encode_response(CommandId.STAT_FILE, ResponseCode.ERROR)

    # --- Directory Operations ---

    async def handle_read_dir(self, session: Session, payload: bytes) -> bytes:
        """Handle ReadDirFromServer — list directory contents."""
        if err := _require_auth(session, CommandId.READ_DIR):
            return err

        dirpath = payload.rstrip(b"\x00").decode(DEFAULT_ENCODING)
        local_path = self.shares.resolve(dirpath, session.username or "")

        if local_path is None or not local_path.is_dir():
            return encode_response(CommandId.READ_DIR, ResponseCode.NOT_FOUND)

        try:
            def _list_dir():
                entries = []
                for entry in sorted(local_path.iterdir()):
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    name = entry.name.encode(DEFAULT_ENCODING) + b"\x00"
                    size = struct.pack("<I", min(int(stat.st_size), 0xFFFFFFFF))
                    is_dir = struct.pack("B", 1 if entry.is_dir() else 0)
                    entries.append(name + size + is_dir)
                return entries

            entries = await asyncio.to_thread(_list_dir)
            count = struct.pack("<I", len(entries))
            entry_data = b"".join(entries)
            return encode_response(CommandId.READ_DIR, ResponseCode.OK, count + entry_data)
        except OSError as e:
            log.error("handler.read_dir_error", path=dirpath, error=str(e))
            return encode_response(CommandId.READ_DIR, ResponseCode.ERROR)

    async def handle_mkdir(self, session: Session, payload: bytes) -> bytes:
        """Handle MkDir — create a directory."""
        if err := _require_auth(session, CommandId.MKDIR):
            return err

        dirpath = payload.rstrip(b"\x00").decode(DEFAULT_ENCODING)
        local_path = self.shares.resolve(dirpath, session.username or "")

        if local_path is None:
            return encode_response(CommandId.MKDIR, ResponseCode.NOT_FOUND)

        share = self.shares.get_share_for_path(dirpath)
        if share and share.read_only:
            return encode_response(CommandId.MKDIR, ResponseCode.PERMISSION_DENIED)

        try:
            await asyncio.to_thread(local_path.mkdir, parents=True, exist_ok=True)
            log.info("handler.mkdir", session=session.id[:8], path=dirpath)
            return encode_response(CommandId.MKDIR, ResponseCode.OK)
        except OSError as e:
            log.error("handler.mkdir_error", path=dirpath, error=str(e))
            return encode_response(CommandId.MKDIR, ResponseCode.ERROR)

    async def handle_rmdir(self, session: Session, payload: bytes) -> bytes:
        """Handle RmDir — remove a directory."""
        if err := _require_auth(session, CommandId.RMDIR):
            return err

        dirpath = payload.rstrip(b"\x00").decode(DEFAULT_ENCODING)
        local_path = self.shares.resolve(dirpath, session.username or "")

        if local_path is None or not local_path.is_dir():
            return encode_response(CommandId.RMDIR, ResponseCode.NOT_FOUND)

        share = self.shares.get_share_for_path(dirpath)
        if share and share.read_only:
            return encode_response(CommandId.RMDIR, ResponseCode.PERMISSION_DENIED)

        try:
            await asyncio.to_thread(local_path.rmdir)
            log.info("handler.rmdir", session=session.id[:8], path=dirpath)
            return encode_response(CommandId.RMDIR, ResponseCode.OK)
        except OSError as e:
            log.error("handler.rmdir_error", path=dirpath, error=str(e))
            return encode_response(CommandId.RMDIR, ResponseCode.ERROR)

    # --- System Queries ---

    async def handle_get_free_mem(self, session: Session, payload: bytes) -> bytes:
        """Handle GetFreeMem — report available disk space."""
        if err := _require_auth(session, CommandId.GET_FREE_MEM):
            return err

        try:
            first_share_path = self.shares.get_first_local_path()
            if first_share_path:
                total, used, free_bytes = await asyncio.to_thread(
                    shutil.disk_usage, str(first_share_path)
                )
            else:
                free_bytes = 0

            mem_data = struct.pack("<Q", free_bytes)
            return encode_response(CommandId.GET_FREE_MEM, ResponseCode.OK, mem_data)
        except OSError:
            return encode_response(CommandId.GET_FREE_MEM, ResponseCode.ERROR)

    async def handle_get_version(self, session: Session, payload: bytes) -> bytes:
        """Handle GetVersion — return server version string."""
        from pcu20 import __version__
        version_str = f"PCU20Net-Python/{__version__}".encode(DEFAULT_ENCODING) + b"\x00"
        return encode_response(CommandId.GET_VERSION, ResponseCode.OK, version_str)
