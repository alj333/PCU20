"""Protocol constants, enums, and data classes."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class SessionState(enum.Enum):
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    DISCONNECTED = "disconnected"


class CommandId(enum.IntEnum):
    """Known PCU20 protocol command IDs.

    These are provisional — actual values must be confirmed via MITM capture.
    The hex values below are placeholders that will be updated once the real
    protocol is captured and analyzed.
    """
    # Authentication
    LOGIN = 0x01
    TERMINATE = 0x02

    # File operations
    OPEN_FILE = 0x10
    CLOSE_FILE = 0x11
    READ_FILE = 0x12
    WRITE_FILE = 0x13
    STAT_FILE = 0x14
    CHMOD_FILE = 0x15
    ACCESS_FILE = 0x16
    SEARCH_IN_FILE = 0x17
    READ_LINES = 0x18
    GET_LINE_POS = 0x19
    GET_NUM_LINES = 0x1A
    NUMBER_FILE = 0x1B

    # Directory operations
    READ_DIR = 0x20
    GET_DIR_LIST = 0x21
    MKDIR = 0x22
    RMDIR = 0x23

    # System queries
    GET_FREE_MEM = 0x30
    GET_VERSION = 0x31
    GET_VERSION_EX = 0x32


class ResponseCode(enum.IntEnum):
    """Response status codes (provisional)."""
    OK = 0x00
    ERROR = 0x01
    AUTH_REQUIRED = 0x02
    AUTH_FAILED = 0x03
    NOT_FOUND = 0x04
    PERMISSION_DENIED = 0x05
    ALREADY_EXISTS = 0x06
    UNKNOWN_COMMAND = 0xFF


# Wire format constants (provisional — update after capture analysis)
FRAME_HEADER_SIZE = 4  # bytes for length prefix
BYTE_ORDER = "little"
MAX_FRAME_SIZE = 1024 * 1024  # 1 MB safety limit
DEFAULT_ENCODING = "latin-1"  # Common in industrial protocols


@dataclass
class Frame:
    """A decoded protocol frame."""
    command_id: int
    payload: bytes
    raw: bytes = field(default=b"", repr=False)


@dataclass
class FileHandle:
    """An open file handle tracked per session."""
    handle_id: int
    path: str
    mode: str  # "r" or "w"
    position: int = 0
