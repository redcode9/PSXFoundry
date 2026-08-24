import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from popfe_runtime import RuntimePaths
from psxfoundry.gui import (
    confirm_conversion_without_fix,
    label_path_chooser,
    load_dropped_image,
    load_theme_image,
    write_exception_log,
)
from psxfoundry.registry import CompatibilityAssetError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GuiPathTests(unittest.TestCase):
    def test_path_chooser_uses_a_text_label(self):
        class Button:
            def configure(self, **options):
                self.options = options

        chooser = type("Chooser", (), {"folder_button": Button()})()
        label_path_chooser(chooser, "Choose folder...")

        self.assertEqual(chooser.folder_button.options["text"], "Choose folder...")
        self.assertGreaterEqual(chooser.folder_button.options["width"], 8)

    def test_dropped_image_accepts_a_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cover.png"
            Image.new("RGB", (4, 3), "red").save(path)

            image = load_dropped_image(
                str(path), lambda *_args, **_kwargs: self.fail("network used")
            )
            self.assertEqual(image.size, (4, 3))
            image.close()

    def test_theme_image_keeps_the_uppercase_match(self):
        requested = []

        def load(_theme, _disc_id, _work_dir, filename):
            requested.append(filename)
            return "image" if filename == "PIC0.PNG" else None

        image = load_theme_image(load, "theme", "DISC", "/tmp", "PIC0")

        self.assertEqual(image, "image")
        self.assertEqual(requested, ["PIC0.PNG"])

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

        self.assertIn("Open game folder...", ui)
        self.assertIn("Add disc image...", ui)
        self.assertIn("Include every disc found in the folder", ui)
        self.assertIn("import_all_discs_variable", ui)
        self.assertIn("def import_folder(", source)
        self.assertIn("def load_disc(", source)

    def test_psp_gui_resolves_and_accepts_per_disc_sbi_files(self):
        ui = ET.parse(REPOSITORY_ROOT / "pop-fe-psp.ui")
        object_ids = {
            element.attrib.get("id")
            for element in ui.iter("object")
        }
        source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")

        self.assertTrue(
            {f"sbi{index}_button" for index in range(1, 6)} <= object_ids
        )
        self.assertIn("resolve_sbi(", source)
        self.assertIn("sbi_files=request.sbi_files", source)
        self.assertIn("Continue with the generated fallback?", source)
        self.assertIn("The game could hang or crash", source)
        self.assertIn("SBI: not needed", source)
        self.assertIn("def _planned_sbi_magic", source)

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

        self.assertIn("class PspApp(DesktopAppMixin):", psp_source)
        self.assertIn("class Ps3App(DesktopAppMixin):", ps3_source)
        self.assertNotIn("class CompletionDialog", psp_source + ps3_source)

    def test_psp_conversion_runs_behind_a_modal_progress_dialog(self):
        source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")
        dialogs = (REPOSITORY_ROOT / "psxfoundry/gui.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("ConversionTask(", source)
        self.assertIn("threading.Thread(", dialogs)
        self.assertIn("self.root.after(50, self._poll)", dialogs)
        self.assertIn("set_phase('Creating EBOOT.PBP...')", source)
        self.assertIn("set_phase('Validating EBOOT.PBP...')", source)
        self.assertIn('self.protocol("WM_DELETE_WINDOW", lambda: None)', dialogs)
        self.assertIn("self.grab_set()", dialogs)

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

    def test_psp_gui_explains_and_resets_manual_settings(self):
        ui = (REPOSITORY_ROOT / "pop-fe-psp.ui").read_text(encoding="utf-8")
        source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")

        for marker in (
            "Automatic settings are recommended",
            "Restore automatic settings",
            "Keep raw CD audio",
            "Use direct single-disc layout",
            "Negative moves left; positive moves right",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, ui)
        self.assertIn("def on_restore_automatic", source)
        self.assertIn("render_workflow_summary", source)
        self.assertNotIn("('undither', self.builder.get_variable", source)

    def test_psp_gui_uses_content_sized_workflow_sections(self):
        ui = ET.parse(REPOSITORY_ROOT / "pop-fe-psp.ui")
        objects = {
            element.attrib.get("id"): element
            for element in ui.iter("object")
        }

        for object_id in ("discs", "frame1", "frame7", "output_frame"):
            with self.subTest(object_id=object_id):
                self.assertEqual(objects[object_id].attrib["class"], "ttk.Labelframe")

        frame_sizes = {
            property_.text
            for object_ in objects.values()
            if object_.attrib.get("class") in {"ttk.Frame", "ttk.Labelframe"}
            for property_ in object_.findall("property")
            if property_.attrib.get("name") in {"height", "width"}
        }
        self.assertNotIn("200", frame_sizes)

        source = (REPOSITORY_ROOT / "pop-fe-psp.py").read_text(encoding="utf-8")
        self.assertIn("def _configure_layout(self):", source)
        self.assertIn("root.minsize(1040, 680)", source)

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

    def test_ps3_gui_matches_the_desktop_workflow_layout(self):
        ui = ET.parse(REPOSITORY_ROOT / "pop-fe-ps3.ui")
        objects = {
            element.attrib.get("id"): element
            for element in ui.iter("object")
        }
        source = (REPOSITORY_ROOT / "pop-fe-ps3.py").read_text(
            encoding="utf-8"
        )

        for object_id in ("discs", "nameofgame", "frame3", "outputpkg", "options"):
            with self.subTest(object_id=object_id):
                self.assertEqual(
                    objects[object_id].attrib["class"], "ttk.Labelframe"
                )
        self.assertIn("def on_toggle_advanced(self):", source)
        self.assertIn("get_object('options', self.master).grid_remove()", source)
        self.assertIn("root.minsize(1040, 680)", source)
        self.assertIn("Find preview audio online", ET.tostring(ui.getroot(), encoding="unicode"))

    def test_cli_requires_an_explicit_missing_fix_override(self):
        source = (REPOSITORY_ROOT / "pop-fe.py").read_text(encoding="utf-8")

        self.assertIn("--allow-missing-fixes", source)
        self.assertIn("allow_missing_fixes=args.allow_missing_fixes", source)


if __name__ == "__main__":
    unittest.main()
