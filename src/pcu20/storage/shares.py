"""Share manager — maps virtual CNC paths to local filesystem paths."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import structlog

from pcu20.config import ShareConfig

log = structlog.get_logger()


class ShareManager:
    """Manages virtual path → local filesystem mappings.

    The CNC uses Linux-style paths like /NCDATA/subdir/file.mpf.
    The first path component is the share name, which maps to a local directory.
    """

    def __init__(self, shares: list[ShareConfig]) -> None:
        self._shares: dict[str, ShareConfig] = {}
        for share in shares:
            name = share.name.upper()
            self._shares[name] = share
            # Ensure the local path exists
            local = Path(share.path)
            local.mkdir(parents=True, exist_ok=True)
            log.info("shares.registered", name=name, path=str(local.resolve()))

    def resolve(self, virtual_path: str, username: str) -> Path | None:
        """Resolve a CNC virtual path to a local filesystem path.

        Args:
            virtual_path: Path as seen by the CNC (e.g., "/NCDATA/part1.mpf").
            username: The authenticated username (for future per-user access control).

        Returns:
            Local Path if valid and within a share, None otherwise.
        """
        # Normalize: use PurePosixPath since the CNC uses Linux paths
        vpath = PurePosixPath(virtual_path)

        # Extract share name (first component after root)
        parts = vpath.parts
        if len(parts) < 2:
            # Root path "/" — could list shares
            return None

        share_name = parts[1].upper()  # parts[0] is "/"
        share = self._shares.get(share_name)
        if share is None:
            log.warning("shares.not_found", share=share_name, path=virtual_path)
            return None

        # Build the local path from remaining components
        local_base = Path(share.path).resolve()
        if len(parts) > 2:
            relative = PurePosixPath(*parts[2:])
            local_path = local_base / str(relative)
        else:
            local_path = local_base

        # Security: prevent path traversal
        try:
            resolved = local_path.resolve()
            if not str(resolved).startswith(str(local_base)):
                log.warning("shares.path_traversal", path=virtual_path, resolved=str(resolved))
                return None
        except (OSError, ValueError):
            return None

        return resolved

    def get_share_for_path(self, virtual_path: str) -> ShareConfig | None:
        """Get the ShareConfig for a virtual path."""
        vpath = PurePosixPath(virtual_path)
        parts = vpath.parts
        if len(parts) < 2:
            return None
        share_name = parts[1].upper()
        return self._shares.get(share_name)

    def get_first_local_path(self) -> Path | None:
        """Get the local path of the first configured share."""
        if self._shares:
            first = next(iter(self._shares.values()))
            return Path(first.path).resolve()
        return None

    def list_shares(self) -> list[dict[str, str | bool]]:
        """Return share info for the web dashboard."""
        return [
            {
                "name": cfg.name,
                "path": str(Path(cfg.path).resolve()),
                "read_only": cfg.read_only,
            }
            for cfg in self._shares.values()
        ]
