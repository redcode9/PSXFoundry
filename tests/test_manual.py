import importlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image


popfe = importlib.import_module("pop-fe")


class ManualTests(unittest.TestCase):
    def test_repeated_zip_conversion_uses_separate_work_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "manual.zip"
            page = io.BytesIO()
            Image.new("RGB", (320, 480), "white").save(page, format="PNG")
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("page.png", page.getvalue())

            first = Path(popfe.create_manual(str(archive), "SCES02834", str(root)))
            second = Path(popfe.create_manual(str(archive), "SCES02834", str(root)))

            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertNotEqual(first.parent, second.parent)


if __name__ == "__main__":
    unittest.main()
