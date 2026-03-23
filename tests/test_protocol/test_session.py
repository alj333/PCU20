"""Tests for session state machine."""

from pcu20.protocol.session import Session
from pcu20.protocol.types import SessionState


class TestSession:
    def test_initial_state(self):
        s = Session(peer_address=("192.168.1.10", 12345))
        assert s.state == SessionState.CONNECTED
        assert s.peer_ip == "192.168.1.10"
        assert not s.is_authenticated
        assert s.commands_processed == 0

    def test_authenticate(self):
        s = Session(peer_address=("10.0.0.1", 1234))
        s.authenticate("PCU20_USER")
        assert s.is_authenticated
        assert s.username == "PCU20_USER"
        assert s.state == SessionState.AUTHENTICATED

    def test_disconnect(self):
        s = Session(peer_address=("10.0.0.1", 1234))
        s.authenticate("user")
        s.disconnect()
        assert s.state == SessionState.DISCONNECTED
        assert not s.is_authenticated

    def test_file_handles(self):
        s = Session(peer_address=("10.0.0.1", 1234))
        h1 = s.allocate_handle("/NCDATA/test.mpf", "r")
        h2 = s.allocate_handle("/NCDATA/other.mpf", "w")
        assert h1 != h2
        assert len(s.file_handles) == 2

        handle = s.close_handle(h1)
        assert handle is not None
        assert handle.path == "/NCDATA/test.mpf"
        assert len(s.file_handles) == 1

    def test_close_all_handles(self):
        s = Session(peer_address=("10.0.0.1", 1234))
        s.allocate_handle("/a", "r")
        s.allocate_handle("/b", "r")
        s.close_all_handles()
        assert len(s.file_handles) == 0

    def test_summary(self):
        s = Session(peer_address=("192.168.1.50", 6743))
        s.authenticate("PCU20_USER")
        summary = s.summary()
        assert summary["peer_ip"] == "192.168.1.50"
        assert summary["username"] == "PCU20_USER"
        assert summary["state"] == "authenticated"
        assert "uptime" in summary
