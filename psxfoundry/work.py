"""Atomic file operations for conversion work."""

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import shutil
import sys
import uuid


def _clonefile(source, destination):
    if sys.platform != "darwin":
        return False
    try:
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        clonefile = library.clonefile
        clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        clonefile.restype = ctypes.c_int
        result = clonefile(
            os.fsencode(source),
            os.fsencode(destination),
            0,
        )
        return result == 0
    except (AttributeError, OSError):
        return False


def clone_or_copy(source, destination, *, clone_function=None):
    """Create an atomic APFS clone when possible, otherwise copy the file."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination:
        return "same"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.partial"
    )
    cloner = clone_function or _clonefile
    try:
        cloned = cloner(source, temporary)
        if not cloned:
            shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        return "clone" if cloned else "copy"
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def atomic_output(destination):
    """Yield a sibling path and publish it only after successful completion."""
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.partial"
    )
    try:
        yield temporary
        if not temporary.is_file():
            raise FileNotFoundError("atomic output was not created")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
