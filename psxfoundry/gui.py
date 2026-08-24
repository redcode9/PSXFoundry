"""Shared desktop application helpers."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import tkinter.ttk as ttk
import traceback

from PIL import Image

from popfe_runtime import RuntimePaths
from psxfoundry.registry import CompatibilityAssetError


@dataclass(frozen=True)
class ImportedDisc:
    cue_file: str
    original_cue_file: str
    image_file: str
    disc_id: str


class CompletionDialog(tk.Toplevel):
    def __init__(self, root, message):
        super().__init__(root)
        self.title("Conversion complete")
        self.resizable(False, False)
        self.transient(root)
        ttk.Label(self, text=message).pack(
            fill="both", expand=True, padx=24, pady=(20, 12)
        )
        ttk.Button(self, text="Close", command=self.destroy).pack(
            pady=(0, 20)
        )


class ConversionProgressDialog(tk.Toplevel):
    def __init__(self, root, message="Preparing conversion..."):
        super().__init__(root)
        self.title("Conversion in progress")
        self.resizable(False, False)
        self.transient(root)
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        self.status = tk.StringVar(self, value=message)
        ttk.Label(self, textvariable=self.status, anchor="center").pack(
            fill="x", padx=24, pady=(20, 12)
        )
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=320)
        self.progress.pack(fill="x", padx=24, pady=(0, 20))
        self.progress.start(12)
        self.grab_set()

    def set_phase(self, message):
        self.status.set(message)

    def close(self):
        self.progress.stop()
        if self.grab_current() == self:
            self.grab_release()
        self.destroy()


class ConversionTask:
    def __init__(
        self,
        root,
        runtime,
        component,
        error_title,
        worker,
        on_complete,
    ):
        self.root = root
        self.runtime = runtime
        self.component = component
        self.error_title = error_title
        self.worker = worker
        self.on_complete = on_complete
        self.events = queue.Queue()
        self.dialog = None
        self.running = False

    def start(self):
        if self.running:
            return False
        self.running = True
        self.dialog = ConversionProgressDialog(self.root)
        threading.Thread(target=self._run, daemon=True).start()
        self.root.after(50, self._poll)
        return True

    def _run(self):
        def set_phase(message):
            self.events.put(("phase", message))

        try:
            result = self.worker(set_phase)
        except Exception as error:
            self.events.put(("error", error))
            return
        self.events.put(("complete", result))

    def _poll(self):
        while True:
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                self.root.after(100, self._poll)
                return

            if event == "phase":
                self.dialog.set_phase(value)
                continue

            self.dialog.close()
            self.dialog = None
            self.running = False
            if event == "error":
                show_conversion_error(
                    self.root,
                    self.runtime,
                    self.component,
                    self.error_title,
                    value,
                )
            else:
                self.on_complete(value)
            return


class DesktopAppMixin:
    def _reset_imported_discs(self):
        self.cue_file_orig = None
        self.cue_files = []
        self.real_cue_files = []
        self.image_files = []
        self.disc_ids = []
        self.real_disc_ids = []

    def _record_imported_disc(self, disc):
        self.cue_file_orig = disc.original_cue_file
        self.cue_files.append(disc.cue_file)
        self.real_cue_files.append(disc.original_cue_file)
        self.image_files.append(disc.image_file)
        self.disc_ids.append(disc.disc_id)
        self.real_disc_ids.append(disc.disc_id)

    def _reset_artwork(self):
        for name in (
            'icon0',
            'icon0_tk',
            'pic0',
            'pic0_orig',
            'pic0_path',
            'pic0_tk',
            'pic1',
            'pic1_path',
            'pic1_tk',
            'preview_tk',
        ):
            setattr(self, name, None)
        self.manual = None

    def _set_controls_state(self, state, *object_ids):
        for object_id in object_ids:
            self.builder.get_object(
                object_id, self.master
            ).configure(state=state)

    def _clear_variables(self, *variable_names):
        for variable_name in variable_names:
            self.builder.get_variable(variable_name).set('')

    def _set_disc_initial_directory(self, directory, disc_count=5):
        for disc_number in range(1, disc_count + 1):
            self.builder.get_object(
                f'disc{disc_number}', self.master
            ).configure(initialdir=directory)

    def on_reset(self):
        self.init_data()

    def on_theme_selected(self, _event):
        self.master.configure(cursor='watch')
        try:
            self._theme = self.builder.get_object('theme', self.master).get()
            self.update_assets()
        finally:
            self.master.configure(cursor='')

    def on_youtube_audio(self):
        if self.preview_audio_search is not None:
            select_preview_audio(
                self.master, self.builder, self.preview_audio_search
            )

    def _render_artwork_preview(self, name, size, temporary_paths):
        preview = render_image_preview(
            getattr(self, name),
            size,
            self.subdir + name.upper() + '.PNG',
            self.builder.get_object(name + '_canvas', self.master),
            temporary_paths,
        )
        setattr(self, name + '_tk', preview)

    def _load_background_artwork(
        self, popfe, temporary_paths, disc_id, game
    ):
        self.pic1 = load_background_image(
            popfe,
            self.pic1_path,
            self._theme,
            disc_id,
            self.subdir,
            game,
            self.cue_file_orig,
        )
        if self.pic1:
            self._render_artwork_preview(
                'pic1', (128, 80), temporary_paths
            )

    def on_dir_changed(self, event):
        self.pkgdir = event.widget.cget('path')
        self.update_prefs()

    def _refresh_conversion_plan_with_prompt(self):
        return build_plan_with_missing_fix_prompt(
            self.master, self._refresh_conversion_plan
        )


def clear_temporary_paths(paths, *, verbose=False):
    for value in paths:
        path = Path(value)
        if verbose:
            print("Removing temporary path", path)
        try:
            path.unlink()
        except IsADirectoryError:
            try:
                path.rmdir()
            except OSError:
                pass
        except FileNotFoundError:
            pass


def reset_work_directory(work_dir, temporary_paths):
    clear_temporary_paths(temporary_paths)
    temporary_paths.clear()
    shutil.rmtree(work_dir, ignore_errors=True)
    Path(work_dir).mkdir(parents=True)
    temporary_paths.append(str(work_dir))


def read_preferences(path):
    with Path(path).open('r', encoding='utf-8') as preferences_file:
        return dict(
            line.split(':', 1)
            for line in preferences_file.read().splitlines()
        )


def write_preferences(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as preferences_file:
        for key, value in values:
            preferences_file.write(f'{key}:{value}\n')


def import_disc_image(
    popfe,
    source_path,
    disc_number,
    temporary_paths,
    work_dir,
    *,
    is_psp=False,
):
    cue_file, original_cue_file, image_file = popfe.process_disk_file(
        source_path,
        disc_number,
        temporary_paths,
        subdir=work_dir,
    )
    scan_path = str(Path(work_dir) / f'TMP{disc_number:02}.iso')
    disc_id, _ = popfe.get_disc_id(
        cue_file,
        original_cue_file,
        scan_path,
        is_psp=is_psp,
    )
    temporary_paths.append(scan_path)
    return ImportedDisc(
        cue_file=cue_file,
        original_cue_file=original_cue_file,
        image_file=image_file,
        disc_id=disc_id,
    )


def label_path_chooser(chooser, text="Choose..."):
    chooser.folder_button.configure(text=text, width=max(8, len(text)))


def choose_image(parent, title):
    path = filedialog.askopenfilename(
        parent=parent,
        title=title,
        filetypes=(
            ('Image files', '*.png *.PNG *.jpg *.JPG'),
            ('All files', '*'),
        ),
    )
    if not path or not Path(path).is_file():
        return None, None
    return path, Image.open(path)


def load_theme_image(loader, theme, disc_id, work_dir, name):
    return loader(theme, disc_id, work_dir, f'{name}.PNG') or loader(
        theme, disc_id, work_dir, f'{name}.png'
    )


def load_background_image(
    popfe,
    image_path,
    theme,
    disc_id,
    work_dir,
    game,
    cue_file,
):
    if image_path:
        return Image.open(image_path)
    if theme:
        image = load_theme_image(
            popfe.get_image_from_theme,
            theme,
            disc_id,
            work_dir,
            'PIC1',
        )
        if image:
            return image
    return popfe.get_pic1_from_game(disc_id, game, cue_file)


def load_dropped_image(value, fetch):
    try:
        if Path(value).is_file():
            return Image.open(value)
    except (OSError, ValueError):
        pass

    match = re.search(r'src=["\']([^"\']+)', value)
    if not match:
        return None
    try:
        response = fetch(match.group(1), stream=True)
    except Exception:
        return None
    if response.status_code != 200:
        return None
    return Image.open(io.BytesIO(response.content))


def render_image_preview(image, size, output_path, canvas, temporary_paths):
    temporary_paths.append(str(output_path))
    image.resize(size, Image.Resampling.HAMMING).save(output_path)
    preview = tk.PhotoImage(file=output_path)
    canvas.delete('all')
    canvas.create_image(0, 0, image=preview, anchor='nw')
    return preview


def find_preview_audio_url(title, search):
    result = search(f"{title} ps1 ost")
    if not result or not result.results:
        return None
    return f"https://www.youtube.com/watch?v={result.results[0].video_id}"


def select_preview_audio(root, builder, search):
    root.configure(cursor='watch')
    try:
        title = builder.get_variable('title_variable').get()
        audio_url = find_preview_audio_url(title, search)
        if audio_url:
            builder.get_variable('snd0_variable').set(audio_url)
    finally:
        root.configure(cursor='')


def build_plan_with_missing_fix_prompt(parent, build_plan):
    try:
        return build_plan()
    except CompatibilityAssetError as error:
        if not confirm_conversion_without_fix(parent, error):
            return None
        return build_plan(allow_missing_fixes=True)


def write_exception_log(
    runtime: RuntimePaths,
    component: str,
    exception_type: type[BaseException],
    exception: BaseException,
    traceback_object,
):
    """Persist one GUI callback failure and return its log path."""
    log_path = runtime.new_log_path(component)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"PSXFoundry component: {component}\n")
        log.write(f"Platform: {runtime.platform}\n")
        log.write(f"Executable: {runtime.executable}\n\n")
        traceback.print_exception(
            exception_type,
            exception,
            traceback_object,
            file=log,
        )
    return log_path


def show_conversion_error(parent, runtime, component, title, error):
    try:
        log_path = write_exception_log(
            runtime,
            component,
            type(error),
            error,
            error.__traceback__,
        )
    except Exception:
        log_path = None

    message = str(error)
    if log_path is not None:
        message += f"\n\nDiagnostic log: {log_path}"
    messagebox.showerror(title, message, parent=parent)


def install_tk_error_handler(
    root,
    runtime: RuntimePaths,
    component: str,
    title: str,
) -> None:
    """Show an actionable dialog for exceptions raised by Tk callbacks."""

    def report_callback_exception(exception_type, exception, traceback_object):
        log_path = write_exception_log(
            runtime,
            component,
            exception_type,
            exception,
            traceback_object,
        )
        traceback.print_exception(
            exception_type,
            exception,
            traceback_object,
            file=sys.stderr,
        )
        messagebox.showerror(
            title,
            f"{exception}\n\nDiagnostic log: {log_path}",
            parent=root,
        )

    root.report_callback_exception = report_callback_exception


def confirm_conversion_without_fix(parent, error) -> bool:
    """Ask before omitting an unavailable compatibility fix."""
    return messagebox.askyesno(
        "Compatibility fix unavailable",
        (
            f"{error}\n\n"
            "Continuing without this fix may prevent the game from starting "
            "or cause gameplay problems. PSXFoundry cannot guarantee the "
            "result.\n\nContinue without this fix?"
        ),
        icon="warning",
        default="no",
        parent=parent,
    )
