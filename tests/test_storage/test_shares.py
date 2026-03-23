"""Tests for share management."""

from pathlib import Path

import pytest

from pcu20.config import ShareConfig
from pcu20.storage.shares import ShareManager


@pytest.fixture
def share_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ncdata"
    d.mkdir()
    (d / "test.mpf").write_text("N10 G0 X0\n")
    sub = d / "subdir"
    sub.mkdir()
    (sub / "nested.mpf").write_text("N10 G1 X10\n")
    return d


@pytest.fixture
def share_manager(share_dir: Path) -> ShareManager:
    return ShareManager([
        ShareConfig(name="NCDATA", path=str(share_dir), read_only=False),
        ShareConfig(name="BACKUP", path=str(share_dir), read_only=True),
    ])


class TestShareManager:
    def test_resolve_root_file(self, share_manager: ShareManager, share_dir: Path):
        result = share_manager.resolve("/NCDATA/test.mpf", "user")
        assert result is not None
        assert result == (share_dir / "test.mpf").resolve()

    def test_resolve_nested_file(self, share_manager: ShareManager, share_dir: Path):
        result = share_manager.resolve("/NCDATA/subdir/nested.mpf", "user")
        assert result is not None
        assert result.name == "nested.mpf"

    def test_resolve_share_root(self, share_manager: ShareManager, share_dir: Path):
        result = share_manager.resolve("/NCDATA", "user")
        assert result is not None
        assert result == share_dir.resolve()

    def test_resolve_unknown_share(self, share_manager: ShareManager):
        result = share_manager.resolve("/UNKNOWN/file.mpf", "user")
        assert result is None

    def test_resolve_root_path(self, share_manager: ShareManager):
        result = share_manager.resolve("/", "user")
        assert result is None

    def test_path_traversal_blocked(self, share_manager: ShareManager):
        result = share_manager.resolve("/NCDATA/../../../etc/passwd", "user")
        assert result is None

    def test_case_insensitive_share_name(self, share_manager: ShareManager):
        result = share_manager.resolve("/ncdata/test.mpf", "user")
        assert result is not None

    def test_get_share_for_path(self, share_manager: ShareManager):
        share = share_manager.get_share_for_path("/NCDATA/test.mpf")
        assert share is not None
        assert share.name == "NCDATA"
        assert share.read_only is False

    def test_get_share_read_only(self, share_manager: ShareManager):
        share = share_manager.get_share_for_path("/BACKUP/test.mpf")
        assert share is not None
        assert share.read_only is True

    def test_list_shares(self, share_manager: ShareManager):
        shares = share_manager.list_shares()
        assert len(shares) == 2
        names = {s["name"] for s in shares}
        assert "NCDATA" in names
        assert "BACKUP" in names
