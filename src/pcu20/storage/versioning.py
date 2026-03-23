"""NC program version tracking using git."""

from __future__ import annotations

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

    def init_share(self, share_path: Path) -> None:
        """Initialize version tracking for a share directory."""
        if not self.config.enabled:
            return

        if self.config.strategy == "git":
            self._init_git(share_path)
        elif self.config.strategy == "snapshots":
            snapshot_dir = share_path / ".versions"
            snapshot_dir.mkdir(exist_ok=True)

    def _init_git(self, share_path: Path) -> None:
        """Initialize a git repo in the share directory if not already present."""
        try:
            import git
            repo_path = share_path.resolve()
            if (repo_path / ".git").exists():
                self._repos[str(repo_path)] = git.Repo(repo_path)
                log.info("versioning.git_loaded", path=str(repo_path))
            else:
                repo = git.Repo.init(repo_path)
                # Create .gitignore for version metadata
                gitignore = repo_path / ".gitignore"
                if not gitignore.exists():
                    gitignore.write_text(".versions/\n")
                repo.index.add([".gitignore"])
                repo.index.commit("Initialize NC program repository")
                self._repos[str(repo_path)] = repo
                log.info("versioning.git_initialized", path=str(repo_path))
        except ImportError:
            log.warning("versioning.git_not_available", msg="gitpython not installed")
        except Exception as e:
            log.error("versioning.git_init_error", path=str(share_path), error=str(e))

    async def on_file_written(self, file_path: Path, metadata: dict) -> None:
        """Called after a file write completes — creates a version snapshot."""
        if not self.config.enabled:
            return

        if self.config.strategy == "git":
            await self._git_commit(file_path, metadata)
        else:
            await self._snapshot(file_path)

    async def _git_commit(self, file_path: Path, metadata: dict) -> None:
        """Commit the file change to git."""
        try:
            import git

            # Find the repo for this file
            repo_path = None
            for path_str, repo in self._repos.items():
                if str(file_path.resolve()).startswith(path_str):
                    repo_path = path_str
                    break

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

    async def _snapshot(self, file_path: Path) -> None:
        """Create a timestamped snapshot copy."""
        try:
            share_root = file_path.parent
            # Walk up to find .versions directory
            while share_root.parent != share_root:
                if (share_root / ".versions").exists():
                    break
                share_root = share_root.parent

            versions_dir = share_root / ".versions"
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
            for path_str, repo in self._repos.items():
                if str(file_path.resolve()).startswith(path_str):
                    rel_path = file_path.resolve().relative_to(path_str)
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
        results = []
        share_root = file_path.parent
        while share_root.parent != share_root:
            if (share_root / ".versions").exists():
                break
            share_root = share_root.parent

        versions_dir = share_root / ".versions"
        if not versions_dir.exists():
            return results

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
