import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from popfe_gui import confirm_conversion_without_fix, write_exception_log
from popfe_runtime import RuntimePaths
from psxfoundry.registry import CompatibilityAssetError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GuiPathTests(unittest.TestCase):
    def test_gui_sources_do_not_write_relative_preferences_or_theme_files(self):
        for filename in ("pop-fe-psp.py", "pop-fe-ps3.py"):
            source = (REPOSITORY_ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertNotIn("with open('pop-fe-psp.config'", source)
                self.assertNotIn("with open('pop-fe-ps3.config'", source)
                self.assertNotIn("disc_id, 'pop-fe-psp-work'", source)
                self.assertIn("popfe_runtime.resource_path", source)
                self.assertIn("popfe_runtime.application_work_dir", source)
                self.assertIn("PREFERENCES_PATH", source)
                self.assertIn('"PSXFOUNDRY_GUI_SMOKE_TEST"', source)
                self.assertIn("root.update_idletasks()", source)

    def test_gui_exception_log_uses_macos_log_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime = RuntimePaths.detect(
                platform="darwin",
                frozen=False,
                source_file=REPOSITORY_ROOT / "pop-fe.py",
                executable=root / "python3",
                home=root / "home",
                environ={},
                cwd=root / "cwd",
            )

            try:
                raise RuntimeError("conversion failed")
            except RuntimeError as error:
                log_path = write_exception_log(
                    runtime,
                    "psp",
                    type(error),
                    error,
                    error.__traceback__,
                )

            self.assertEqual(log_path.parent, runtime.log_dir)
            contents = log_path.read_text(encoding="utf-8")
            self.assertIn("conversion failed", contents)
            self.assertIn("RuntimeError", contents)
            self.assertIn("Platform: darwin", contents)

    def test_missing_fix_confirmation_states_the_conversion_risk(self):
        error = CompatibilityAssetError(
            "test-rule",
            "apply_ppf",
            "fix.ppf",
            "file is missing",
        )
        with patch("tkinter.messagebox.askyesno", return_value=True) as ask:
            accepted = confirm_conversion_without_fix(None, error)

        self.assertTrue(accepted)
        message = ask.call_args.args[1]
        self.assertIn("may prevent the game from starting", message)
        self.assertIn("cannot guarantee the result", message)
        self.assertEqual(ask.call_args.kwargs["default"], "no")

    def test_psp_gui_exposes_folder_and_manual_disc_import(self):
        ui = (REPOSITORY_ROOT / "pop-fe-psp.ui").read_text(encoding="utf-8")
        source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")

        self.assertIn("Import folder...", ui)
        self.assertIn("Add disc...", ui)
        self.assertIn("Import all discs in folder", ui)
        self.assertIn("import_all_discs_variable", ui)
        self.assertIn("def import_folder(", source)
        self.assertIn("def load_disc(", source)

    def test_psp_gui_uses_automatic_planning_and_validation(self):
        source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")
        for marker in (
            "build_psp_plan",
            "prepare_target_inputs",
            "validate_generated_eboot",
            "render_target_workflow_report",
            "no_libcrypt=True",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        self.assertNotIn("popfe.apply_ppf_fixes", source)

    def test_gui_apps_share_dialogs_and_use_specific_class_names(self):
        psp_source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")
        ps3_source = (REPOSITORY_ROOT / "pop-fe-ps3.py").read_text(encoding="utf-8")

        self.assertIn("class PspApp:", psp_source)
        self.assertIn("class Ps3App:", ps3_source)
        self.assertNotIn("class FinishedDialog", psp_source + ps3_source)

    def test_psp_gui_keeps_compatibility_overrides_collapsed(self):
        ui = ET.parse(REPOSITORY_ROOT / "pop-fe-psp.ui")
        object_ids = {
            element.attrib.get("id")
            for element in ui.iter("object")
        }
        self.assertTrue(
            {"target", "plan_summary", "advanced_button", "frame4"}
            <= object_ids
        )
        source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")
        self.assertIn("get_object('frame4', self.master).grid_remove()", source)

    def test_ps3_gui_uses_target_specific_planning(self):
        source = (REPOSITORY_ROOT / "pop-fe-ps3.py").read_text(encoding="utf-8")
        for marker in (
            "build_target_plan",
            "prepare_target_inputs",
            "read_ps3_configs",
            "render_target_workflow_report",
            "no_libcrypt=True",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        self.assertNotIn("popfe.apply_ppf_fixes", source)

    def test_cli_requires_an_explicit_missing_fix_override(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")

        self.assertIn("--allow-missing-fixes", source)
        self.assertIn("allow_missing_fixes=args.allow_missing_fixes", source)


if __name__ == "__main__":
    unittest.main()
