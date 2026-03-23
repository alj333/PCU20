"""Shared test fixtures."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pcu20.config import AppConfig, AuthConfig, ShareConfig, UserConfig


@pytest.fixture
def tmp_share(tmp_path: Path) -> Path:
    """Create a temporary share directory with sample NC files."""
    share_dir = tmp_path / "NCDATA"
    share_dir.mkdir()

    # Create sample NC program files
    (share_dir / "part1.mpf").write_text(
        "N10 G90 G54\nN20 G0 X0 Y0 Z50\nN30 M30\n"
    )
    (share_dir / "part2.mpf").write_text(
        "N10 G91\nN20 G1 X10 F500\nN30 M30\n"
    )

    subdir = share_dir / "subprograms"
    subdir.mkdir()
    (subdir / "tool_change.spf").write_text("N10 T1 M6\nN20 M30\n")

    return share_dir


@pytest.fixture
def app_config(tmp_share: Path) -> AppConfig:
    """Create a test AppConfig with a temporary share."""
    return AppConfig(
        auth=AuthConfig(
            users=[UserConfig(username="PCU20_USER", password="testpass")]
        ),
        shares=[
            ShareConfig(name="NCDATA", path=str(tmp_share), read_only=False),
        ],
    )
