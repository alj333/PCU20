"""Tests for the protocol frame codec."""

from pcu20.protocol.codec import FrameCodec, encode_response
from pcu20.protocol.types import FRAME_HEADER_SIZE


class TestFrameCodec:
    def test_empty_buffer(self):
        codec = FrameCodec()
        assert codec.feed(b"") == []

    def test_incomplete_header(self):
        codec = FrameCodec()
        assert codec.feed(b"\x00\x00") == []
        assert codec.buffered_bytes == 2

    def test_incomplete_frame(self):
        codec = FrameCodec()
        # Length says 10 bytes, but we only provide 5
        length = (10).to_bytes(FRAME_HEADER_SIZE, "little")
        assert codec.feed(length + b"\x01\x02\x03\x04\x05") == []

    def test_single_complete_frame(self):
        codec = FrameCodec()
        payload = b"\x01\x02\x03"  # cmd_id=0x01, payload=\x02\x03
        length = len(payload).to_bytes(FRAME_HEADER_SIZE, "little")
        frames = codec.feed(length + payload)
        assert len(frames) == 1
        assert frames[0].command_id == 0x01
        assert frames[0].payload == b"\x02\x03"

    def test_multiple_frames_in_one_feed(self):
        codec = FrameCodec()
        frame1 = (2).to_bytes(FRAME_HEADER_SIZE, "little") + b"\x10\xAA"
        frame2 = (3).to_bytes(FRAME_HEADER_SIZE, "little") + b"\x20\xBB\xCC"
        frames = codec.feed(frame1 + frame2)
        assert len(frames) == 2
        assert frames[0].command_id == 0x10
        assert frames[1].command_id == 0x20

    def test_split_across_feeds(self):
        codec = FrameCodec()
        full = (3).to_bytes(FRAME_HEADER_SIZE, "little") + b"\x05\xAA\xBB"
        # Split in the middle
        assert codec.feed(full[:4]) == []  # Just the header
        frames = codec.feed(full[4:])  # The payload
        assert len(frames) == 1
        assert frames[0].command_id == 0x05

    def test_reset(self):
        codec = FrameCodec()
        codec.feed(b"\x00\x00\x00")
        assert codec.buffered_bytes == 3
        codec.reset()
        assert codec.buffered_bytes == 0


class TestEncodeResponse:
    def test_basic_response(self):
        resp = encode_response(0x01, 0x00, b"\xAA")
        # Header (4 bytes LE) + command_id (1) + status (1) + payload (1)
        assert len(resp) == FRAME_HEADER_SIZE + 3
        length = int.from_bytes(resp[:4], "little")
        assert length == 3
        assert resp[4] == 0x01  # command_id
        assert resp[5] == 0x00  # status
        assert resp[6] == 0xAA  # payload

    def test_empty_payload(self):
        resp = encode_response(0x31, 0x00)
        length = int.from_bytes(resp[:4], "little")
        assert length == 2  # just command_id + status
