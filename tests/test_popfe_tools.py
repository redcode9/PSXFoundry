import importlib
import sys
import unittest
from pathlib import Path

from popfe_runtime import RuntimePaths


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
popfe = importlib.import_module("pop-fe")


class BackendToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.runtime = RuntimePaths.detect(
            platform=sys.platform,
            frozen=False,
            source_file=REPOSITORY_ROOT / "pop-fe.py",
            executable=sys.executable,
            cwd=Path("/"),
        )

    def test_required_repository_resources_resolve_outside_project_cwd(self):
        self.assertEqual(
            self.runtime.resource_path("PS3LOGO.DAT", required=True),
            REPOSITORY_ROOT / "PS3LOGO.DAT",
        )
        self.assertTrue(
            self.runtime.resource_path(
                "pspconfigs/Neo Planet/SLPS-00323.bin",
                required=True,
            ).is_file()
        )

    def test_python_helpers_use_absolute_repository_paths(self):
        sign_command = self.runtime.tool_command("sign3", "image.bin")
        cue_command = self.runtime.tool_command("cue2cu2", "image.cue")

        self.assertEqual(Path(sign_command[0]), Path(sys.executable).absolute())
        self.assertEqual(Path(sign_command[1]), REPOSITORY_ROOT / "sign3.py")
        self.assertEqual(
            Path(cue_command[1]),
            REPOSITORY_ROOT / "Cue2cu2" / "cue2cu2.py",
        )
        self.assertTrue(all(Path(path).is_absolute() for path in sign_command[:2]))
        self.assertTrue(all(Path(path).is_absolute() for path in cue_command[:2]))

    def test_backend_has_no_direct_conversion_helper_commands(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")
        deprecated_commands = (
            "['./atracdenc",
            "['ffmpeg'",
            "['ffmpeg.exe'",
            "['python3', './sign3.py'",
            "['python3','PSL1GHT/tools/ps3py/pkg.py'",
            "['pkg.exe'",
            "['xdelta3'",
            "['python3', 'Cue2cu2/cue2cu2.py'",
            "['chdman'",
            "['python3', 'binmerge/binmerge'",
            "['./lcp'",
            "['lcp.exe'",
            "['./psx-undither/build/psxund'",
            "['psxund.exe'",
        )

        for command in deprecated_commands:
            with self.subTest(command=command):
                self.assertNotIn(command, source)

    def test_cli_uses_runtime_workspace_instead_of_current_directory(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")
        self.assertIn(
            "popfe_runtime.application_work_dir('cli', 'pop-fe-work')",
            source,
        )
        self.assertIn(
            "atexit.register(popfe_runtime.remove_work_dir, work_dir)",
            source,
        )
        self.assertIn("popfe_runtime.remove_work_dir(work_dir)", source)
        self.assertNotIn("subdir = 'pop-fe-work/'", source)
        self.assertNotIn("os.unlink('NORMAL01.iso')", source)

    def test_retroarch_thumbnail_runs_before_pbp_mutates_images(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")
        thumbnail = "if args.retroarch_thumbnail_dir:"
        pbp = "if args.retroarch_pbp_dir:"
        self.assertLess(source.index(thumbnail), source.index(pbp))

    def test_cli_plans_and_isolates_each_output_target(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")
        main = source[source.index('if __name__ == "__main__":'):]

        self.assertIn("target_plans = {", main)
        self.assertIn("prepare_target_inputs(", main)
        self.assertIn("target_plans['ps3']", main)
        self.assertIn("target_plans.get('retroarch')", main)
        self.assertNotIn("apply_ppf_fixes(", main)
        self.assertNotIn("patch_libcrypt(", main)

    def test_generated_cues_reference_staged_images(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")

        self.assertIn("copy_file(cue_file, tmpbin)", source)
        self.assertIn("copy_file(ccd['FILE'], tmpbin)", source)
        self.assertIn("retarget_cue(tmpcue, tmpcue", source)

    def test_retroarch_writes_sbi_only_for_libcrypt_discs(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")

        self.assertEqual(
            source.count("i < len(magic_word) and magic_word[i]"),
            2,
        )

    def test_exact_sbi_data_replaces_generated_subchannels(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")

        self.assertIn("sbi_files=None", source)
        self.assertIn("load_sbi(", source)
        self.assertIn(".to_pbp_subchannels()", source)
        self.assertIn("sbi_files=sbi_files", source)
        self.assertIn("--sbi", source)

    def test_explicit_zero_disables_even_a_selected_sbi(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")
        function = source[
            source.index("def prepare_target_inputs(") :
            source.index("def write_target_report(")
        ]

        self.assertLess(
            function.index("disc.libcrypt_magic_word == 0"),
            function.index("elif sbi_file"),
        )

    def test_cooked_iso_conversion_keeps_a_source_warning(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")

        self.assertIn("REM PSXFOUNDRY COOKED_ISO", source)
        self.assertIn("convert_iso_to_bin(cue_file, tmpbin)", source)

    def test_psp_config_flags_apply_to_planned_defaults(self):
        config = popfe._load_psp_configs(
            ["SCUS00001"],
            ["SCUS00001"],
            ["game.cue"],
            [None],
            force_ntsc=True,
            cdda=True,
        )[0]

        self.assertEqual(config[0x09] & 0x20, 0x20)
        self.assertEqual(config[0x0B] & 0x10, 0x10)
        self.assertEqual(config[0x8D] & 0x20, 0x20)
        self.assertEqual(config[0x8F] & 0x10, 0x10)

    def test_ps3_ntsc_flag_merges_every_matching_command(self):
        config = bytes([
            0x20, 0, 0, 0, 0, 0, 0, 0,
            0x20, 0, 0, 0, 1, 0, 0, 0,
        ])

        merged = popfe._force_ntsc_ps3_config(config)

        self.assertEqual(merged[4], 0x40)
        self.assertEqual(merged[12], 0x41)


if __name__ == "__main__":
    unittest.main()
