"""Authentication handling for PCU20 connections."""

from __future__ import annotations

import structlog

from pcu20.config import AuthConfig

log = structlog.get_logger()


class Authenticator:
    """Validates login credentials against configured users."""

    def __init__(self, config: AuthConfig) -> None:
        self._users = {u.username: u.password for u in config.users}

    def validate(self, username: str, password: str) -> bool:
        """Check if the username/password pair is valid.

        Note: The real PCU20 protocol may use a hashed or obfuscated password.
        This implementation supports plaintext for now and will be updated
        once the actual auth mechanism is captured via MITM proxy.
        """
        expected = self._users.get(username)
        if expected is None:
            log.warning("auth.unknown_user", username=username)
            return False

        if expected != password:
            log.warning("auth.bad_password", username=username)
            return False

        log.info("auth.success", username=username)
        return True
