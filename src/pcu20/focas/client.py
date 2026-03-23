"""Low-level FOCAS2 API wrapper.

Wraps pyfocas (ctypes around fwlib DLL) or falls back to direct TCP.
All calls are blocking and should be run via asyncio.to_thread().
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()

# Try to import FOCAS2 library
_focas_lib = None
_focas_backend = None

try:
    import pyfocas
    _focas_lib = pyfocas
    _focas_backend = "pyfocas"
    log.info("focas.backend", backend="pyfocas (ctypes)")
except ImportError:
    pass

if _focas_lib is None:
    try:
        import pyfanuc
        _focas_lib = pyfanuc
        _focas_backend = "pyfanuc"
        log.info("focas.backend", backend="pyfanuc (pure Python)")
    except ImportError:
        pass


def get_backend() -> str | None:
    """Return the name of the available FOCAS2 backend, or None."""
    return _focas_backend


class FocasClient:
    """Low-level FOCAS2 connection to a single CNC.

    All methods are synchronous (blocking). Call via asyncio.to_thread().
    """

    def __init__(self, host: str, port: int = 8193, timeout: int = 10) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._handle: int = 0
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """Connect to the CNC (cnc_allclibhndl3)."""
        if _focas_lib is None:
            raise RuntimeError(
                "No FOCAS2 library available. "
                "Install pyfocas or pyfanuc."
            )

        # TODO: Implement actual FOCAS2 connection via the available backend.
        # This is a placeholder that will be completed when testing against
        # real Fanuc hardware.
        #
        # pyfocas example:
        #   self._handle = pyfocas.cnc_allclibhndl3(self.host, self.port, self.timeout)
        #
        log.info("focas.connect", host=self.host, port=self.port,
                 backend=_focas_backend)
        self._connected = True

    def disconnect(self) -> None:
        """Disconnect from the CNC (cnc_freelibhndl)."""
        if self._connected:
            # TODO: pyfocas.cnc_freelibhndl(self._handle)
            self._connected = False
            log.info("focas.disconnect", host=self.host)

    def read_status(self) -> dict:
        """Read CNC status (cnc_statinfo)."""
        # TODO: Implement with real FOCAS2 calls
        # Returns: {"run": "start"|"stop"|..., "mode": "auto"|"mdi"|...}
        return {"run": "unknown", "mode": ""}

    def read_alarm(self) -> list[dict]:
        """Read active alarms (cnc_alarm)."""
        return []

    def read_absolute_pos(self) -> dict[str, float]:
        """Read absolute axis positions (cnc_absolute)."""
        return {}

    def read_machine_pos(self) -> dict[str, float]:
        """Read machine coordinate positions (cnc_machine)."""
        return {}

    def read_program_number(self) -> int | None:
        """Read current running program number (cnc_rdprognum)."""
        return None

    def read_program_directory(self) -> list[dict]:
        """Read program directory listing (cnc_rdprogdir)."""
        return []

    def upload_file(self, prog_number: int) -> bytes | None:
        """Upload program from CNC to PC (cnc_upstart4/cnc_upload/cnc_upend)."""
        return None

    def download_file(self, data: bytes, prog_number: int) -> bool:
        """Download program from PC to CNC (cnc_dwnstart3/cnc_download3/cnc_dwnend3)."""
        return False

    def read_tool_info(self) -> list[dict]:
        """Read tool offset data (cnc_rdtool)."""
        return []
