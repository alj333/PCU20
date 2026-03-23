"""FOCAS2-specific data structures and enums."""

from __future__ import annotations

from enum import Enum


class FocasRunState(str, Enum):
    """CNC run state from cnc_statinfo."""
    RESET = "reset"
    STOP = "stop"
    HOLD = "hold"
    START = "start"
    MSTR = "mstr"     # manual start


class FocasMode(str, Enum):
    """CNC operating mode."""
    MDI = "mdi"
    AUTO = "auto"
    EDIT = "edit"
    JOG = "jog"
    REF = "ref"       # reference point return
    HANDLE = "handle"  # handwheel


class FocasAlarm:
    """Represents an active CNC alarm."""

    def __init__(self, code: int, message: str = "", axis: str = "") -> None:
        self.code = code
        self.message = message
        self.axis = axis

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "axis": self.axis}
