"""Small GUI integration helpers shared by the packaged applications."""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.ttk as ttk
import traceback
from typing import Type

from popfe_runtime import RuntimePaths


class FinishedDialog(tk.Toplevel):
    def __init__(self, root, message):
        super().__init__(root)
        tk.Label(self, text=message).pack(
            fill="both", expand=True, padx=20, pady=20
        )
        tk.Button(self, text="Continue", command=self.destroy).pack(side="bottom")


class ConversionDialog(tk.Toplevel):
    def __init__(self, root, message="Preparing conversion..."):
        super().__init__(root)
        self.title("Creating EBOOT.PBP")
        self.resizable(False, False)
        self.transient(root)
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        self.status = tk.StringVar(self, value=message)
        ttk.Label(self, textvariable=self.status, anchor="center").pack(
            fill="x", padx=24, pady=(20, 12)
        )
        self.progress = ttk.Progressbar(
            self,
            mode="indeterminate",
            length=320,
        )
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


def write_exception_log(
    runtime: RuntimePaths,
    component: str,
    exception_type: Type[BaseException],
    exception: BaseException,
    traceback_object,
):
    """Persist one GUI callback failure and return its diagnostic log path."""
    log_path = runtime.new_log_path(component)
    with open(log_path, "w", encoding="utf-8") as log:
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
        from tkinter import messagebox

        messagebox.showerror(
            title,
            f"{exception}\n\nDiagnostic log: {log_path}",
            parent=root,
        )

    root.report_callback_exception = report_callback_exception


def confirm_conversion_without_fix(parent, error) -> bool:
    """Ask before omitting an unavailable compatibility fix."""
    from tkinter import messagebox

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
