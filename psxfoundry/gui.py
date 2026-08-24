"""Shared desktop application helpers."""

from __future__ import annotations

from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import tkinter.ttk as ttk
import traceback

from popfe_runtime import RuntimePaths
from psxfoundry.registry import CompatibilityAssetError


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


def find_preview_audio_url(title, search):
    result = search(f"{title} ps1 ost")
    if not result or not result.results:
        return None
    return f"https://www.youtube.com/watch?v={result.results[0].video_id}"


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
