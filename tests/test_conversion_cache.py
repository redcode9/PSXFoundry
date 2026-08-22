import tempfile
import unittest
from pathlib import Path

from psxfoundry.cache import AnalysisCache
from psxfoundry.disc import analyze_disc


SECTOR_SIZE = 2352


class AnalysisCacheTests(unittest.TestCase):
    def make_cue(self, root):
        image = root / "Track.BIN"
        image.write_bytes(bytes([0x31]) * SECTOR_SIZE)
        cue = root / "game.cue"
        cue.write_text(
            'FILE "track.bin" BINARY\n'
            '  TRACK 01 MODE2/2352\n'
            '    INDEX 01 00:00:00\n',
            encoding="utf-8",
        )
        return cue, image

    def test_reuses_unchanged_cue_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cue, _ = self.make_cue(root)
            cache = AnalysisCache(root / "cache")
            calls = []

            first = cache.analyze(cue, lambda path: (calls.append(path), analyze_disc(path))[1])
            second = cache.analyze(cue, lambda path: (calls.append(path), analyze_disc(path))[1])

            self.assertEqual(first, second)
            self.assertEqual(calls, [cue])
            self.assertEqual(len(tuple((root / "cache" / "objects").iterdir())), 1)

    def test_invalidates_when_an_image_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cue, image = self.make_cue(root)
            cache = AnalysisCache(root / "cache")
            cache.analyze(cue, analyze_disc)
            image.write_bytes(bytes([0x42]) * SECTOR_SIZE * 2)

            self.assertIsNone(cache.get(cue))

    def test_ignores_corrupt_cache_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cue, _ = self.make_cue(root)
            cache = AnalysisCache(root / "cache")
            cache.analyze(cue, analyze_disc)
            object_path = next((root / "cache" / "objects").iterdir())
            object_path.write_text("broken", encoding="utf-8")

            self.assertIsNone(cache.get(cue))


if __name__ == "__main__":
    unittest.main()
