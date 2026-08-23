import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from psxfoundry.sbi import (
    SbiDownloadError,
    SbiError,
    find_local_sbi,
    load_sbi,
    parse_sbi,
    parse_sbi_index,
    resolve_online_sbi,
    resolve_sbi,
)


def bcd(value):
    return (value // 10) * 16 + value % 10


def sbi_payload(sectors, marker=0):
    payload = bytearray(b"SBI\x00")
    for sector in sectors:
        minute, remainder = divmod(sector, 60 * 75)
        second, frame = divmod(remainder, 75)
        payload.extend((bcd(minute), bcd(second), bcd(frame), 1))
        payload.extend(bytes((0x41, 1, 1, 0, 0, marker, 0, 0, 0, marker)))
    return bytes(payload)


class SbiTests(unittest.TestCase):
    def test_parser_reads_magic_word_and_builds_pbp_records(self):
        payload = sbi_payload((14105, 14110, 16167, 16172))

        data = parse_sbi(payload, expected_magic_word=0x8001)
        subchannels = data.to_pbp_subchannels()

        self.assertEqual(len(data.entries), 4)
        self.assertEqual(data.magic_word, 0x8001)
        self.assertEqual(len(subchannels), 72)
        self.assertEqual(subchannels[:12].hex(), "ffffffff00000000ffffffff")
        self.assertEqual(subchannels[-12:], b"\xff" * 12)
        self.assertEqual(int.from_bytes(subchannels[12:16], "little"), 13955)

    def test_parser_rejects_bad_records(self):
        with self.assertRaisesRegex(SbiError, "header"):
            parse_sbi(b"bad")
        with self.assertRaisesRegex(SbiError, "truncated"):
            parse_sbi(b"SBI\x00broken")
        with self.assertRaisesRegex(SbiError, "magic word"):
            parse_sbi(
                sbi_payload((14105, 14110)),
                expected_magic_word=1,
            )
        with self.assertRaisesRegex(SbiError, "outside the disc"):
            parse_sbi(sbi_payload((14105, 14110)), sector_count=100)

    def test_parser_rejects_incomplete_sector_pair(self):
        with self.assertRaisesRegex(SbiError, "incomplete"):
            parse_sbi(sbi_payload((14105,)))

    def test_local_discovery_prefers_matching_disc_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = root / "Crash Bash.CUE"
            disc.touch()
            expected = root / "crash bash.sBi"
            expected.write_bytes(sbi_payload((14105, 14110)))
            (root / "other.sbi").touch()

            self.assertEqual(find_local_sbi(disc), expected.resolve())

    def test_local_discovery_accepts_serial_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = root / "Game.cue"
            disc.touch()
            expected = root / "SCES_028.34.sbi"
            expected.write_bytes(sbi_payload((14105, 14110)))

            self.assertEqual(
                find_local_sbi(disc, "SCES02834"), expected.resolve()
            )

    def test_resolver_uses_local_sbi_before_online_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = root / "Game.cue"
            disc.touch()
            sbi = root / "Game.sbi"
            sbi.write_bytes(sbi_payload((14105, 14110)))

            result = resolve_sbi(
                disc,
                "SCES02834",
                expected_magic_word=0x8000,
                cache_dir=root / "cache",
            )

            self.assertEqual(result.selection.path, sbi.resolve())
            self.assertEqual(result.selection.origin, "local")
            self.assertIsNone(result.error)

    def test_index_keeps_only_supported_https_archives(self):
        html = b"""
            <a href="sbifiles/Crash [SCES-02834] sbi.7z">ok</a>
            <a href="http://example.com/SLES-00001.7z">bad</a>
            <a href="images/SCES-00002.7z">bad</a>
        """

        index = parse_sbi_index(html)

        self.assertEqual(tuple(index), ("SCES02834",))
        self.assertEqual(len(index["SCES02834"]), 1)

    def test_online_resolver_downloads_validated_sbi_and_reuses_cache(self):
        payload = sbi_payload((14105, 14110), marker=1)
        html = b'<a href="sbifiles/Game [SCES-02834] sbi.7z">file</a>'
        calls = []

        def fetch(url, maximum_size):
            calls.append(url)
            return html if url.endswith("sbifiles.html") else b"archive"

        with tempfile.TemporaryDirectory() as directory:
            with patch("psxfoundry.sbi._extract_sbi", return_value=payload):
                first = resolve_online_sbi(
                    "SCES02834",
                    expected_magic_word=0x8000,
                    sector_count=20000,
                    cache_dir=directory,
                    fetch=fetch,
                )
                second = resolve_online_sbi(
                    "SCES02834",
                    expected_magic_word=0x8000,
                    sector_count=20000,
                    cache_dir=directory,
                    fetch=lambda *_: self.fail("cache was not used"),
                )

            self.assertEqual(first.origin, "downloaded")
            self.assertEqual(second.origin, "cached")
            self.assertEqual(load_sbi(first.path).sha256, first.data.sha256)
            self.assertEqual(len(calls), 2)

    def test_online_resolver_does_not_guess_between_revisions(self):
        html = b"""
            <a href="sbifiles/Game v1 [SCES-02834] sbi.7z">one</a>
            <a href="sbifiles/Game v2 [SCES-02834] sbi.7z">two</a>
        """
        payloads = [
            sbi_payload((14105, 14110), marker=1),
            sbi_payload((14105, 14110), marker=2),
        ]

        def fetch(url, maximum_size):
            return html if url.endswith("sbifiles.html") else b"archive"

        with tempfile.TemporaryDirectory() as directory:
            with patch("psxfoundry.sbi._extract_sbi", side_effect=payloads):
                with self.assertRaisesRegex(SbiDownloadError, "multiple"):
                    resolve_online_sbi(
                        "SCES02834",
                        expected_magic_word=0x8000,
                        cache_dir=directory,
                        fetch=fetch,
                    )


if __name__ == "__main__":
    unittest.main()
