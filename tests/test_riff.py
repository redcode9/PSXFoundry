import struct
import tempfile
import unittest
from pathlib import Path

from riff import RiffFormatError, copy_riff, parse_riff


def riff_chunk(name, payload):
    padding = b"\x00" if len(payload) % 2 else b""
    return name + struct.pack("<I", len(payload)) + payload + padding


class RiffTests(unittest.TestCase):
    def write_riff(self, directory, body, trailing=b""):
        path = Path(directory) / "SND0.AT3"
        path.write_bytes(
            b"RIFF" + struct.pack("<I", len(body)) + body + trailing
        )
        return path

    def test_ignores_non_chunk_data_after_atrac_payload(self):
        fmt = struct.pack(
            "<HHIIHH",
            0x0270,
            2,
            44100,
            8268,
            192,
            0,
        ) + bytes(16)
        audio = b"\xa3\x00\x00\x02" + bytes(188)
        invalid_tail = b"\xa3\x00\x00m\xac\xb2\x38\xd9"
        body = (
            b"WAVE"
            + riff_chunk(b"fmt ", fmt)
            + riff_chunk(b"data", audio)
            + invalid_tail
        )

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_riff(directory, body, trailing=bytes(32))
            result = parse_riff(path)

        self.assertEqual(result["fmt "]["compression_code"], 0x0270)
        self.assertEqual(result["data"]["data"], audio)

    def test_rejects_invalid_chunk_before_audio_data(self):
        body = b"WAVE" + b"\xa3\x00\x00m" + struct.pack("<I", 0)

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_riff(directory, body)
            with self.assertRaisesRegex(RiffFormatError, "chunk identifier"):
                parse_riff(path)

    def test_copy_ignores_invalid_data_after_pcm_payload(self):
        fmt = struct.pack("<HHIIHH", 1, 2, 44100, 176400, 4, 16)
        audio = bytes(range(32))
        body = (
            b"WAVE"
            + riff_chunk(b"fmt ", fmt)
            + riff_chunk(b"data", audio)
            + b"\xa3\x00\x00m\xac\xb2\x38\xd9"
        )

        with tempfile.TemporaryDirectory() as directory:
            source = self.write_riff(directory, body)
            destination = Path(directory) / "copy.wav"
            copy_riff(source, destination)
            result = parse_riff(destination)

        self.assertEqual(result["data"]["data"], audio)

    def test_rejects_truncated_chunk(self):
        body = b"WAVE" + b"fmt " + struct.pack("<I", 32) + bytes(4)

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_riff(directory, body)
            with self.assertRaisesRegex(RiffFormatError, "truncated RIFF chunk"):
                parse_riff(path)


if __name__ == "__main__":
    unittest.main()
