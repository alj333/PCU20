"""NC program version tracking using git."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import structlog

from pcu20.config import VersioningConfig

log = structlog.get_logger()


class VersionManager:
    """Tracks NC program versions using git or simple file snapshots."""

    def __init__(self, config: VersioningConfig) -> None:
        self.config = config
        self._repos: dict[str, object] = {}  # path -> git.Repo
        self._share_roots: set[str] = set()  # resolved share root paths

    def init_share(self, share_path: Path) -> None:
        """Initialize version tracking for a share directory."""
        if not self.config.enabled:
            return

        resolved = share_path.resolve()
        self._share_roots.add(str(resolved))

        if self.config.strategy == "git":
            self._init_git(resolved)
        elif self.config.strategy == "snapshots":
            snapshot_dir = resolved / ".versions"
            snapshot_dir.mkdir(exist_ok=True)

    def _init_git(self, share_path: Path) -> None:
        """Initialize a git repo in the share directory if not already present."""
        try:
            import git
            if (share_path / ".git").exists():
                self._repos[str(share_path)] = git.Repo(share_path)
                log.info("versioning.git_loaded", path=str(share_path))
            else:
                repo = git.Repo.init(share_path)
                gitignore = share_path / ".gitignore"
                if not gitignore.exists():
                    gitignore.write_text(".versions/\n")
                repo.index.add([".gitignore"])
                repo.index.commit("Initialize NC program repository")
                self._repos[str(share_path)] = repo
                log.info("versioning.git_initialized", path=str(share_path))
        except ImportError:
            log.warning("versioning.git_not_available", msg="gitpython not installed")
        except Exception as e:
            log.error("versioning.git_init_error", path=str(share_path), error=str(e))

    async def on_file_written(self, file_path: Path, metadata: dict) -> None:
        """Called after a file write completes — creates a version snapshot."""
        if not self.config.enabled:
            return

        if self.config.strategy == "git":
            await asyncio.to_thread(self._git_commit_sync, file_path, metadata)
        elif self.config.strategy == "snapshots":
            await asyncio.to_thread(self._snapshot_sync, file_path)

    def _git_commit_sync(self, file_path: Path, metadata: dict) -> None:
        """Commit the file change to git (runs in thread)."""
        try:
            import git

            repo_path = self._find_repo_for(file_path)
            if repo_path is None:
                return

            repo = self._repos[repo_path]
            rel_path = file_path.resolve().relative_to(repo_path)

            repo.index.add([str(rel_path)])

            machine_ip = metadata.get("machine_ip", "unknown")
            username = metadata.get("username", "unknown")
            msg = f"Update {rel_path.name} from {machine_ip} ({username})"
            repo.index.commit(msg)

            log.info("versioning.committed", file=str(rel_path), machine=machine_ip)
        except Exception as e:
            log.error("versioning.commit_error", file=str(file_path), error=str(e))

    def _snapshot_sync(self, file_path: Path) -> None:
        """Create a timestamped snapshot copy (runs in thread)."""
        try:
            share_root = self._find_share_root_for(file_path)
            if share_root is None:
                return

            versions_dir = Path(share_root) / ".versions"
            if not versions_dir.exists():
                versions_dir.mkdir(exist_ok=True)

            timestamp = int(time.time())
            snapshot_name = f"{file_path.name}.{timestamp}"
            snapshot_path = versions_dir / snapshot_name

            import shutil
            shutil.copy2(file_path, snapshot_path)

            # Rotate old snapshots
            self._rotate_snapshots(versions_dir, file_path.name)

            log.info("versioning.snapshot_created", file=str(file_path), snapshot=snapshot_name)
        except Exception as e:
            log.error("versioning.snapshot_error", file=str(file_path), error=str(e))

    def _find_repo_for(self, file_path: Path) -> str | None:
        """Find the git repo path that contains this file."""
        resolved = str(file_path.resolve())
        for path_str in self._repos:
            if resolved.startswith(path_str + "/") or resolved.startswith(path_str + "\\"):
                return path_str
        return None

    def _find_share_root_for(self, file_path: Path) -> str | None:
        """Find the share root that contains this file (bounded, won't walk to /)."""
        resolved = str(file_path.resolve())
        for root in self._share_roots:
            if resolved.startswith(root + "/") or resolved.startswith(root + "\\"):
                return root
        return None

    def _rotate_snapshots(self, versions_dir: Path, base_name: str) -> None:
        """Remove old snapshots beyond max_snapshots."""
        prefix = f"{base_name}."
        snapshots = sorted(
            [f for f in versions_dir.iterdir() if f.name.startswith(prefix)],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for old in snapshots[self.config.max_snapshots:]:
            old.unlink()

    def get_history(self, file_path: Path) -> list[dict]:
        """Get version history for a file."""
        if self.config.strategy == "git":
            return self._git_history(file_path)
        return self._snapshot_history(file_path)

    def _git_history(self, file_path: Path) -> list[dict]:
        """Get git log for a file."""
        try:
            repo_path = self._find_repo_for(file_path)
            if repo_path is None:
                return []
            repo = self._repos[repo_path]
            rel_path = file_path.resolve().relative_to(repo_path)
            commits = list(repo.iter_commits(paths=str(rel_path), max_count=50))
            return [
                {
                    "hash": c.hexsha[:8],
                    "message": c.message.strip(),
                    "author": str(c.author),
                    "date": c.committed_datetime.isoformat(),
                }
                for c in commits
            ]
        except Exception as e:
            log.error("versioning.history_error", file=str(file_path), error=str(e))
        return []

    def _snapshot_history(self, file_path: Path) -> list[dict]:
        """List snapshot versions for a file."""
        share_root = self._find_share_root_for(file_path)
        if share_root is None:
            return []

        versions_dir = Path(share_root) / ".versions"
        if not versions_dir.exists():
            return []

        results = []
        prefix = f"{file_path.name}."
        for snap in sorted(versions_dir.iterdir(), reverse=True):
            if snap.name.startswith(prefix):
                ts_str = snap.name[len(prefix):]
                try:
                    ts = int(ts_str)
                    results.append({
                        "timestamp": ts,
                        "size": snap.stat().st_size,
                        "name": snap.name,
                    })
                except ValueError:
                    continue
        return results
