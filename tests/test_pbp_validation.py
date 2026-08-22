import contextlib
import hashlib
import io
import struct
import tempfile
import unittest
from pathlib import Path

from popstation import popstation
from psxfoundry.pbp import PSISO_BLOCK_SIZE, PbpFormatError, inspect_pbp
from psxfoundry.validation import (
    EbootExpectation,
    validate_eboot,
    validate_generated_eboot,
)


class PbpValidationTests(unittest.TestCase):
    def build_eboot(self, directory, sources, direct_psiso=False):
        station = popstation()
        station.eboot = str(Path(directory) / "EBOOT.PBP")
        station.game_title = "Validation test"
        station.disc_ids = [f"SCUS0000{number + 1}" for number in range(len(sources))]
        station.no_pstitleimg = direct_psiso
        station.configs = [
            bytes([number + 1, 0x55, 0xAA]) for number in range(len(sources))
        ]
        station.magic_word = [0x12340000 + number for number in range(len(sources))]
        station.subchannels = [bytes([number + 1]) * 24 for number in range(len(sources))]
        paths = []
        tocs = []
        for number, source in enumerate(sources):
            path = Path(directory) / f"disc-{number + 1}.bin"
            path.write_bytes(source)
            paths.append(path)
            toc = station.get_toc((str(path), None), len(source))
            tocs.append(bytes(toc).ljust(1020, b"\x00"))
            station.add_img((str(path), toc))
        with contextlib.redirect_stdout(io.StringIO()):
            station.create_pbp()
        return Path(station.eboot), paths, tocs

    def test_inspects_single_disc_and_decodes_every_block(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes(index % 251 for index in range(PSISO_BLOCK_SIZE * 2))
            eboot, _, tocs = self.build_eboot(directory, [source])

            result = inspect_pbp(eboot)

            self.assertEqual(result.psar_wrapper, "PSTITLEIMG")
            self.assertEqual(result.sfo["DISC_ID"], "SCUS00001")
            self.assertEqual(len(result.discs), 1)
            disc = result.discs[0]
            self.assertEqual(disc.disc_id, "SCUS00001")
            self.assertEqual(disc.title, "Validation test")
            self.assertEqual(disc.decoded_size, len(source))
            self.assertEqual(disc.decoded_sha256, hashlib.sha256(source).hexdigest())
            self.assertEqual(disc.toc, tocs[0])
            self.assertEqual(disc.toc_lead_out, len(source) // 2352 + 150)
            self.assertTrue(disc.config_area.startswith(b"\x01\x55\xaa"))
            self.assertEqual(disc.magic_word, 0x12340000)
            self.assertEqual(disc.subchannel_records, 2)

    def test_inspects_direct_single_disc_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes([0x35]) * PSISO_BLOCK_SIZE
            eboot, _, _ = self.build_eboot(directory, [source], direct_psiso=True)

            result = inspect_pbp(eboot)

            self.assertEqual(result.psar_wrapper, "PSISOIMG")
            self.assertEqual(
                result.discs[0].decoded_sha256,
                hashlib.sha256(source).hexdigest(),
            )

    def test_inspects_multidisc_offsets_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = [
                bytes([0x11]) * PSISO_BLOCK_SIZE,
                bytes([0x22]) * PSISO_BLOCK_SIZE,
            ]
            eboot, _, _ = self.build_eboot(directory, sources)

            result = inspect_pbp(eboot)

            self.assertEqual(
                [disc.disc_id for disc in result.discs],
                ["SCUS00001", "SCUS00002"],
            )
            self.assertLess(result.discs[0].offset, result.discs[1].offset)

    def test_rejects_unordered_pbp_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes([0x18]) * PSISO_BLOCK_SIZE
            eboot, _, _ = self.build_eboot(directory, [source])
            with eboot.open("r+b") as handle:
                handle.seek(12)
                handle.write(struct.pack("<I", 0x20))

            with self.assertRaisesRegex(PbpFormatError, "section offsets"):
                inspect_pbp(eboot)

    def test_rejects_invalid_toc(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes([0x19]) * PSISO_BLOCK_SIZE
            eboot, _, _ = self.build_eboot(directory, [source])
            inspection = inspect_pbp(eboot)
            with eboot.open("r+b") as handle:
                handle.seek(inspection.discs[0].offset + 0x802)
                handle.write(b"\x00")

            with self.assertRaisesRegex(PbpFormatError, "TOC lead-in"):
                inspect_pbp(eboot)

    def test_rejects_corrupted_disc_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes(index % 251 for index in range(PSISO_BLOCK_SIZE))
            eboot, _, _ = self.build_eboot(directory, [source])
            inspection = inspect_pbp(eboot)
            payload_offset = inspection.discs[0].offset + 0x100000
            with eboot.open("r+b") as handle:
                handle.seek(payload_offset)
                first = handle.read(1)
                handle.seek(payload_offset)
                handle.write(bytes([first[0] ^ 0xFF]))

            with self.assertRaises(PbpFormatError):
                inspect_pbp(eboot)

    def test_inspects_legacy_blocks_without_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes([0x29]) * PSISO_BLOCK_SIZE
            eboot, _, _ = self.build_eboot(directory, [source])
            inspection = inspect_pbp(eboot)
            checksum_offset = inspection.discs[0].offset + 0x4000 + 8
            with eboot.open("r+b") as handle:
                handle.seek(checksum_offset)
                handle.write(bytes(16))

            result = inspect_pbp(eboot)
            validation = validate_eboot(eboot)

            self.assertEqual(result.discs[0].verified_block_checksums, 0)
            self.assertFalse(validation.ok)
            self.assertIn("blocks without checksums", validation.errors[0])

    def test_validates_expected_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes([0x44]) * PSISO_BLOCK_SIZE
            eboot, _, _ = self.build_eboot(directory, [source])
            expectation = EbootExpectation(
                disc_ids=("SCUS00001",),
                decoded_sizes=(len(source),),
                decoded_sha256=(hashlib.sha256(source).hexdigest(),),
                tocs=(inspect_pbp(eboot).discs[0].toc,),
                configs=(b"\x01\x55\xaa",),
                subchannel_records=(2,),
            )

            result = validate_eboot(eboot, expectation)

            self.assertTrue(result.ok, result.errors)

    def test_reports_plan_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes([0x66]) * PSISO_BLOCK_SIZE
            eboot, _, _ = self.build_eboot(directory, [source])

            result = validate_eboot(
                eboot,
                EbootExpectation(decoded_sizes=(len(source) + PSISO_BLOCK_SIZE,)),
            )

            self.assertFalse(result.ok)
            self.assertIn("disc 1 size", result.errors[0])

    def test_removes_only_invalid_output_and_keeps_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = bytes([0x77]) * PSISO_BLOCK_SIZE
            eboot, _, _ = self.build_eboot(directory, [source])
            with eboot.open("r+b") as handle:
                handle.write(b"BAD!")

            result = validate_generated_eboot(eboot)
            report = eboot.with_suffix(eboot.suffix + ".validation.txt")

            self.assertFalse(result.ok)
            self.assertFalse(eboot.exists())
            self.assertEqual(
                report.read_text(encoding="utf-8").splitlines()[0],
                "Validation: failed",
            )


if __name__ == "__main__":
    unittest.main()
