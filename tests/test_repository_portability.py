import subprocess
import unicodedata
import unittest
from collections import defaultdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def portable_path_key(path):
    """Return the identity used by default case-insensitive macOS volumes."""
    return unicodedata.normalize("NFC", path).casefold()


class RepositoryPortabilityTests(unittest.TestCase):
    def test_public_documentation_replaces_internal_notes(self):
        required = {
            "README.md",
            "CONTRIBUTING.md",
            "THIRD_PARTY_NOTICES.md",
        }
        retired = {
            "COMPATIBILITY.md",
            "README",
            "README.popstation",
            "CREDITS.md",
            "RULES.md",
            "docs/macos-release-checklist.md",
            "docs/macos.md",
            "docs/psp-folder-import.md",
            "docs/source-build.md",
            "docs/superpowers",
            "docs/tools.md",
        }

        self.assertFalse(
            sorted(path for path in required if not (REPOSITORY_ROOT / path).is_file())
        )
        self.assertFalse(
            sorted(path for path in retired if (REPOSITORY_ROOT / path).exists())
        )
        self.assertFalse((REPOSITORY_ROOT / "docs").exists())

    def test_tracked_paths_do_not_collide_when_case_folded(self):
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
        )
        tracked_paths = result.stdout.decode("utf-8").split("\0")
        paths_by_key = defaultdict(list)

        for path in filter(None, tracked_paths):
            paths_by_key[portable_path_key(path)].append(path)

        collisions = [
            paths for paths in paths_by_key.values() if len(paths) > 1
        ]
        details = "\n\n".join("\n".join(paths) for paths in collisions)
        self.assertFalse(
            collisions,
            "Tracked paths collide on a case-insensitive macOS filesystem:\n"
            + details,
        )


if __name__ == "__main__":
    unittest.main()
