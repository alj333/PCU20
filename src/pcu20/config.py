"""Configuration loading and validation using Pydantic."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    bind_address: str = "0.0.0.0"
    base_port: int = 6743
    num_ports: int = Field(default=15, ge=1, le=15)


class WebConfig(BaseModel):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8020


class LoggingConfig(BaseModel):
    level: str = "INFO"
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
    strategy: str = "git"  # "git" or "snapshots"
    max_snapshots: int = 50


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    shares: list[ShareConfig] = Field(default_factory=lambda: [
        ShareConfig(name="NCDATA", path="./ncdata")
    ])
    versioning: VersioningConfig = Field(default_factory=VersioningConfig)


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from a TOML file, falling back to defaults."""
    if path is None:
        path = Path("pcu20.toml")

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return AppConfig.model_validate(data)

    return AppConfig()
