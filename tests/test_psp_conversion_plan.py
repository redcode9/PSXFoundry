import hashlib
import tempfile
import unittest
from pathlib import Path

from psxfoundry.psp_workflow import (
    build_target_plan,
    build_psp_plan,
    expected_decoded_hashes,
    read_ps3_configs,
    read_planned_configs,
    verify_planned_patch_sources,
)
from psxfoundry.report import render_psp_workflow_report
from psxfoundry.registry import (
    CompatibilityAction,
    CompatibilityRegistry,
    CompatibilityRule,
    RuleMatch,
    RuleSource,
)


SECTOR_SIZE = 2352


def rule(actions, *, disc_id="SCUS00001", target="psp"):
    return CompatibilityRule(
        id=f"test-{target}-{disc_id.lower()}",
        title="Test game",
        status="reported",
        match=RuleMatch(disc_ids=(disc_id,)),
        targets=(target,),
        actions=tuple(actions),
        sources=(RuleSource("Test", "https://example.com"),),
        credits=("Test",),
        tests=(),
    )


class PspConversionPlanTests(unittest.TestCase):
    def make_disc(self, root, name, value):
        path = root / name
        path.write_bytes(bytes([value]) * SECTOR_SIZE * 16)
        return path

    def test_plans_each_disc_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.make_disc(root, "disc-1.bin", 0x11)
            second = self.make_disc(root, "disc-2.bin", 0x22)
            registry = CompatibilityRegistry(
                (
                    rule(
                        (CompatibilityAction("set_libcrypt", (("magic_word", 1),)),),
                        disc_id="SCUS00001",
                    ),
                    rule(
                        (CompatibilityAction("set_cdda", (("mode", "raw"),)),),
                        disc_id="SCUS00002",
                    ),
                )
            )

            plan = build_psp_plan(
                (first, second),
                fallback_disc_ids=("SCUS00001", "SCUS00002"),
                registry=registry,
                resource_root=root,
            )

            self.assertEqual(plan.output_disc_ids, ("SCUS00001", "SCUS00002"))
            self.assertEqual(plan.discs[0].libcrypt_magic_word, 1)
            self.assertIsNone(plan.discs[1].libcrypt_magic_word)
            self.assertTrue(plan.use_cdda)
            self.assertEqual(plan.expected_decoded_sizes, (SECTOR_SIZE * 16,) * 2)

    def test_resolves_config_and_output_id_from_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = self.make_disc(root, "disc.bin", 0x33)
            config = root / "profile.bin"
            config.write_bytes(b"profile")
            registry = CompatibilityRegistry(
                (
                    rule(
                        (
                            CompatibilityAction(
                                "set_pops_config",
                                (("path", "profile.bin"), ("sha256", "0" * 64)),
                            ),
                            CompatibilityAction(
                                "set_game_id", (("value", "SCUS99999"),)
                            ),
                        )
                    ),
                )
            )

            plan = build_psp_plan(
                (disc,),
                fallback_disc_ids=("SCUS00001",),
                registry=registry,
                resource_root=root,
            )

            self.assertEqual(plan.output_disc_ids, ("SCUS99999",))
            self.assertEqual(read_planned_configs(plan), (b"profile",))
            self.assertEqual(
                expected_decoded_hashes(plan, (disc,)),
                (hashlib.sha256(disc.read_bytes()).hexdigest(),),
            )

    def test_applies_effective_cdda_and_ntsc_config_bits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = self.make_disc(root, "disc.bin", 0x35)
            config = root / "profile.bin"
            config.write_bytes(bytes(0x90))
            registry = CompatibilityRegistry(
                (
                    rule(
                        (
                            CompatibilityAction(
                                "set_pops_config",
                                (("path", "profile.bin"), ("sha256", "0" * 64)),
                            ),
                        )
                    ),
                )
            )
            plan = build_psp_plan(
                (disc,),
                fallback_disc_ids=("SCUS00001",),
                registry=registry,
                resource_root=root,
            )

            effective = read_planned_configs(
                plan, force_ntsc=True, cdda=True
            )[0]

            self.assertEqual(effective[0x09] & 0x20, 0x20)
            self.assertEqual(effective[0x0B] & 0x10, 0x10)
            self.assertEqual(effective[0x8D] & 0x20, 0x20)
            self.assertEqual(effective[0x8F] & 0x10, 0x10)

    def test_keeps_psp_and_adrenaline_rules_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = self.make_disc(root, "disc.bin", 0x44)
            registry = CompatibilityRegistry(
                (
                    rule(
                        (CompatibilityAction("set_cdda", (("mode", "raw"),)),),
                        target="psp",
                    ),
                    rule(
                        (CompatibilityAction("set_undither", (("enabled", True),)),),
                        target="adrenaline",
                    ),
                )
            )

            plan = build_psp_plan(
                (disc,),
                target="adrenaline",
                fallback_disc_ids=("SCUS00001",),
                registry=registry,
                resource_root=root,
            )

            self.assertFalse(plan.use_cdda)
            self.assertTrue(plan.undither)

            report = render_psp_workflow_report(plan)
            self.assertIn("Target: adrenaline", report)
            self.assertIn("Profile 1: test-adrenaline-scus00001", report)

    def test_rechecks_a_source_before_applying_an_exact_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = self.make_disc(root, "disc.bin", 0x45)
            patch = root / "fix.ppf"
            patch.write_bytes(b"patch")
            registry = CompatibilityRegistry(
                (
                    CompatibilityRule(
                        id="exact-patch",
                        title="Test game",
                        status="reported",
                        match=RuleMatch(
                            disc_ids=("SCUS00001",),
                            sha256=(hashlib.sha256(disc.read_bytes()).hexdigest(),),
                        ),
                        targets=("psp",),
                        actions=(
                            CompatibilityAction(
                                "apply_ppf",
                                (("path", "fix.ppf"), ("sha256", "0" * 64)),
                            ),
                        ),
                        sources=(RuleSource("Test", "https://example.com"),),
                        credits=("Test",),
                        tests=(),
                    ),
                )
            )
            plan = build_psp_plan(
                (disc,),
                fallback_disc_ids=("SCUS00001",),
                registry=registry,
                resource_root=root,
            )
            disc.write_bytes(bytes([0x46]) * SECTOR_SIZE * 16)

            with self.assertRaisesRegex(ValueError, "changed after analysis"):
                verify_planned_patch_sources(plan, (disc,))

    def test_reads_ps3_config_commands_without_the_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disc = self.make_disc(root, "disc.bin", 0x47)
            config = root / "profile.bin"
            config.write_bytes(b"header00" + b"command0")
            registry = CompatibilityRegistry(
                (
                    rule(
                        (
                            CompatibilityAction(
                                "set_pops_config",
                                (("path", "profile.bin"), ("sha256", "0" * 64)),
                            ),
                        ),
                        target="ps3",
                    ),
                )
            )

            plan = build_target_plan(
                (disc,),
                "ps3",
                fallback_disc_ids=("SCUS00001",),
                registry=registry,
                resource_root=root,
            )

            self.assertEqual(read_ps3_configs(plan), (b"command0",))


if __name__ == "__main__":
    unittest.main()
