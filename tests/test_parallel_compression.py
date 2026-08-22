import io
import random
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from popstation import PSISO_BLOCK_SIZE, popstation


class ParallelCompressionTests(unittest.TestCase):
    def encode(self, image, workers, track0_size=None):
        station = popstation()
        station.disc_ids = ["SCUS00001"]
        station.game_title = "Compression test"
        station.compression_workers = workers
        if track0_size is not None:
            station.striptracks = True
            station.add_track0_size(track0_size)
        output = io.BytesIO()
        station.encode_psiso(output, 0, (str(image), bytes(1020)))
        return output.getvalue()

    def decode(self, encoded):
        decoded = bytearray()
        block = 0
        while True:
            index_offset = 0x4000 + block * 32
            data_offset, length = struct.unpack_from(
                "<IH", encoded, index_offset
            )
            if length == 0:
                break
            payload = encoded[
                0x100000 + data_offset:0x100000 + data_offset + length
            ]
            if length < PSISO_BLOCK_SIZE:
                payload = zlib.decompress(payload, wbits=-15)
            decoded.extend(payload)
            block += 1
        return bytes(decoded)

    def test_parallel_output_matches_single_worker_output(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "disc.bin"
            source = random.Random(28).randbytes(PSISO_BLOCK_SIZE * 48)
            image.write_bytes(source)

            sequential = self.encode(image, 1)
            parallel = self.encode(image, 4)

            self.assertEqual(parallel, sequential)
            self.assertEqual(self.decode(parallel), source)

    def test_partial_data_track_is_zero_padded_before_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "mixed.bin"
            data_size = PSISO_BLOCK_SIZE + 123
            image.write_bytes(
                bytes([0x31]) * data_size
                + bytes([0x7A]) * PSISO_BLOCK_SIZE
            )

            encoded = self.encode(image, 4, track0_size=data_size)
            decoded = self.decode(encoded)

            self.assertEqual(decoded[:data_size], bytes([0x31]) * data_size)
            self.assertEqual(
                decoded[data_size:],
                bytes(PSISO_BLOCK_SIZE * 2 - data_size),
            )

    def test_worker_count_must_be_positive(self):
        station = popstation()

        with self.assertRaisesRegex(ValueError, "positive integer"):
            station.compression_workers = 0


if __name__ == "__main__":
    unittest.main()
