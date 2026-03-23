"""Sandboxed filesystem operations for NC program files."""

from __future__ import annotations

import os
from pathlib import Path

import structlog

log = structlog.get_logger()


def safe_read(path: Path) -> bytes | None:
    """Read file contents, returning None on error."""
    try:
        return path.read_bytes()
    except OSError as e:
        log.error("fs.read_error", path=str(path), error=str(e))
        return None


def safe_write(path: Path, data: bytes) -> bool:
    """Write file contents, creating parent dirs as needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return True
    except OSError as e:
        log.error("fs.write_error", path=str(path), error=str(e))
        return False


def list_directory(path: Path) -> list[dict]:
    """List directory contents with metadata."""
    entries = []
    try:
        for entry in sorted(path.iterdir()):
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                continue
    except OSError as e:
        log.error("fs.listdir_error", path=str(path), error=str(e))
    return entries


def get_disk_usage(path: Path) -> dict[str, int]:
    """Get disk usage statistics for the given path."""
    import shutil
    try:
        total, used, free = shutil.disk_usage(str(path))
        return {"total": total, "used": used, "free": free}
    except OSError:
        return {"total": 0, "used": 0, "free": 0}


def count_lines(path: Path) -> int:
    """Count the number of lines in a text file."""
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def search_in_file(path: Path, pattern: str) -> list[tuple[int, str]]:
    """Search for a pattern in a file, returning (line_number, line) tuples."""
    results = []
    try:
        with open(path, "r", encoding="latin-1") as f:
            for i, line in enumerate(f, 1):
                if pattern in line:
                    results.append((i, line.rstrip()))
    except OSError:
        pass
    return results
