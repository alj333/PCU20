"""Configuration loading and validation using Pydantic."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


# --- Protocol configs ---

class PCU20Config(BaseModel):
    """PCU20 TCP server configuration (inbound connections from CNC)."""
    enabled: bool = True
    bind_address: str = "0.0.0.0"
    base_port: int = 6743
    num_ports: int = Field(default=15, ge=1, le=15)


class FocasMachineConfig(BaseModel):
    """Configuration for a single FOCAS2 CNC machine."""
    id: str
    name: str = ""
    host: str
    port: int = 8193
    cnc_type: str = ""    # "fanuc-30i", "fanuc-16i", "fanuc-0i", "mori-mapps"
    enabled: bool = True


class FocasConfig(BaseModel):
    """FOCAS2 client configuration (outbound connections to CNC)."""
    enabled: bool = False
    poll_interval: float = 2.0
    reconnect_interval: float = 30.0
    machines: list[FocasMachineConfig] = Field(default_factory=list)


# --- Shared configs ---

class WebConfig(BaseModel):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8020


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    protocol_trace: bool = True
    trace_file: str = "pcu20_trace.log"
    max_trace_size_mb: int = 100


class UserConfig(BaseModel):
    username: str
    password: str


class AuthConfig(BaseModel):
    users: list[UserConfig] = Field(default_factory=lambda: [
        UserConfig(username="PCU20_USER", password="pcu20")
    ])


class ShareConfig(BaseModel):
    name: str
    path: str
    read_only: bool = False


class VersioningConfig(BaseModel):
    enabled: bool = True
    strategy: str = Field(default="git", pattern="^(git|snapshots)$")
    max_snapshots: int = 50


# --- App config ---

class AppConfig(BaseModel):
    pcu20: PCU20Config = Field(default_factory=PCU20Config)
    focas: FocasConfig = Field(default_factory=FocasConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    shares: list[ShareConfig] = Field(default_factory=lambda: [
        ShareConfig(name="NCDATA", path="./ncdata")
    ])
    versioning: VersioningConfig = Field(default_factory=VersioningConfig)

    @model_validator(mode="before")
    @classmethod
    def _compat_server_key(cls, data: Any) -> Any:
        """Backward compat: map old 'server' key to 'pcu20'."""
        if isinstance(data, dict) and "server" in data and "pcu20" not in data:
            data["pcu20"] = data.pop("server")
        return data


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from a TOML file, falling back to defaults."""
    if path is None:
        path = Path("pcu20.toml")

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return AppConfig.model_validate(data)

    return AppConfig()
