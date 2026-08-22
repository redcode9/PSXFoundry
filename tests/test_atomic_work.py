import tempfile
import unittest
from pathlib import Path

from psxfoundry.work import atomic_output, clone_or_copy


class AtomicWorkTests(unittest.TestCase):
    def test_uses_clone_when_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            destination = root / "output.bin"
            source.write_bytes(b"disc")

            def clone(first, second):
                second.write_bytes(first.read_bytes())
                return True

            mode = clone_or_copy(
                source,
                destination,
                clone_function=clone,
            )

            self.assertEqual(mode, "clone")
            self.assertEqual(destination.read_bytes(), b"disc")

    def test_falls_back_to_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            destination = root / "output.bin"
            source.write_bytes(b"disc")

            mode = clone_or_copy(
                source,
                destination,
                clone_function=lambda _source, _destination: False,
            )

            self.assertEqual(mode, "copy")
            self.assertEqual(destination.read_bytes(), b"disc")

    def test_atomic_output_replaces_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "EBOOT.PBP"
            destination.write_bytes(b"old")

            with atomic_output(destination) as temporary:
                temporary.write_bytes(b"new")
                self.assertEqual(destination.read_bytes(), b"old")

            self.assertEqual(destination.read_bytes(), b"new")

    def test_atomic_output_keeps_existing_file_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "EBOOT.PBP"
            destination.write_bytes(b"old")

            with self.assertRaisesRegex(RuntimeError, "stopped"):
                with atomic_output(destination) as temporary:
                    temporary.write_bytes(b"partial")
                    raise RuntimeError("stopped")

            self.assertEqual(destination.read_bytes(), b"old")
            self.assertEqual(tuple(root.glob("*.partial")), ())


if __name__ == "__main__":
    unittest.main()
