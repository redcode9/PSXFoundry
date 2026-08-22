import io
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from popstation import popstation
from psxfoundry.psp import track_end_offset, whole_disc_modes


BLOCK_SIZE = 0x9300


class WholeDiscModeTests(unittest.TestCase):
    def test_data_only_disc_is_preserved(self):
        self.assertEqual(whole_disc_modes(1, [[]], use_cdda=False), [True])

    def test_atrac_disc_strips_embedded_audio_tracks(self):
        self.assertEqual(
            whole_disc_modes(1, [["track.aea"]], use_cdda=False),
            [False],
        )

    def test_each_disc_is_decided_independently(self):
        self.assertEqual(
            whole_disc_modes(
                3,
                [["disc1.aea"], [], ["disc3.aea"]],
                use_cdda=False,
            ),
            [False, True, False],
        )

    def test_cdda_mode_preserves_every_disc(self):
        self.assertEqual(
            whole_disc_modes(2, [["disc1.aea"], ["disc2.aea"]], use_cdda=True),
            [True, True],
        )


class TrackEndOffsetTests(unittest.TestCase):
    def test_includes_the_final_sector(self):
        track = {
            "INDEX": {
                0: {"STARTSECT": 0, "STOPSECT": 149},
                1: {"STARTSECT": 150, "STOPSECT": 449},
            }
        }

        self.assertEqual(track_end_offset(track), 450 * 2352)

    def test_requires_an_index(self):
        with self.assertRaisesRegex(ValueError, "track has no indexes"):
            track_end_offset({"INDEX": {}})


class PopstationDiscIntegrityTests(unittest.TestCase):
    def decode_image(self, data):
        decoded = bytearray()
        block = 0
        while True:
            index_offset = 0x4000 + block * 32
            data_offset, length = struct.unpack_from("<IH", data, index_offset)
            if length == 0:
                break
            payload = data[0x100000 + data_offset:0x100000 + data_offset + length]
            if length < BLOCK_SIZE:
                payload = zlib.decompress(payload, wbits=-15)
            decoded.extend(payload)
            block += 1
        return bytes(decoded)

    def encode_image(self, image, track0_size):
        station = popstation()
        station.disc_ids = ["SCUS00000"]
        station.game_title = "Integrity test"
        station.striptracks = True
        station.add_track0_size(track0_size)
        output = io.BytesIO()
        station.encode_psiso(output, 0, (str(image), bytes(1020)))
        return output.getvalue()

    def test_full_disc_entry_keeps_trailing_sectors(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "disc.bin"
            source = bytes((index * 17) % 251 for index in range(BLOCK_SIZE * 3))
            image.write_bytes(source)

            encoded = self.encode_image(image, track0_size=None)

            self.assertEqual(self.decode_image(encoded), source)

    def test_atrac_entry_stops_before_audio_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "disc.bin"
            source = bytes((index * 19) % 251 for index in range(BLOCK_SIZE * 3))
            image.write_bytes(source)

            encoded = self.encode_image(image, track0_size=BLOCK_SIZE)

            self.assertEqual(self.decode_image(encoded), source[:BLOCK_SIZE])


if __name__ == "__main__":
    unittest.main()
