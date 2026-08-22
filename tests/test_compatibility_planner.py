import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from psxfoundry.disc import analyze_disc
from psxfoundry.planner import plan_conversion
from psxfoundry.registry import CompatibilityRegistry, load_registry
from psxfoundry.report import render_plan_report


SECTOR_SIZE = 2352
CRASH_BASH_SHA256 = "69e9d985b9d539c4b8eb514a0619993caf26332089d4ffe7d8187dc0f7893649"


class CompatibilityPlannerTests(unittest.TestCase):
    def crash_bash_description(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Crash Bash.bin"
            path.write_bytes(bytes(SECTOR_SIZE))
            base = analyze_disc(path)
        return replace(
            base,
            source=Path("Crash Bash.bin"),
            size=197342208,
            sha256=CRASH_BASH_SHA256,
            disc_id="SCES02834",
            title="CRASH BASH",
            region="pal",
            sector_count=83904,
        )

    def test_plans_exact_crash_bash_corrections(self):
        plan = plan_conversion(
            (self.crash_bash_description(),),
            "psp",
            load_registry(),
        )

        self.assertEqual(plan.rule_id, "crash-bash-sces02834-europe")
        self.assertEqual(
            [action.kind for action in plan.actions],
            [
                "preserve_disc",
                "apply_ppf",
                "set_libcrypt",
                "set_pops_config",
                "set_compression",
            ],
        )
        self.assertEqual(plan.expected_decoded_sizes, (197342208,))

    def test_unknown_audio_disc_uses_lossless_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "audio.bin"
            image.write_bytes(bytes(SECTOR_SIZE * 4))
            cue = root / "audio.cue"
            cue.write_text(
                'FILE "audio.bin" BINARY\n'
                "  TRACK 01 MODE2/2352\n"
                "    INDEX 01 00:00:00\n"
                "  TRACK 02 AUDIO\n"
                "    INDEX 01 00:00:02\n",
                encoding="utf-8",
            )
            disc = analyze_disc(cue)

            plan = plan_conversion((disc,), "adrenaline", CompatibilityRegistry(()))

            self.assertEqual(
                [action.kind for action in plan.actions],
                ["preserve_disc", "set_cdda", "set_compression"],
            )
            self.assertEqual(plan.actions[1].get("mode"), "raw")
            self.assertTrue(plan.assumptions)

    def test_unknown_revision_gets_no_patch(self):
        disc = replace(self.crash_bash_description(), sha256="0" * 64)

        plan = plan_conversion((disc,), "psp", load_registry())

        self.assertIsNone(plan.rule_id)
        self.assertNotIn(
            "apply_ppf",
            [action.kind for action in plan.actions],
        )

    def test_report_contains_profile_actions_and_unverified_state(self):
        disc = replace(self.crash_bash_description(), sha256="0" * 64)
        plan = plan_conversion((disc,), "psp", load_registry())

        report = render_plan_report(plan)

        self.assertIn("Profile: lossless-default", report)
        self.assertIn("Preserve the complete disc image", report)
        self.assertIn("Unverified:", report)


if __name__ == "__main__":
    unittest.main()
