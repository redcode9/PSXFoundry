PSXFoundry for macOS (Apple Silicon)
=====================================

Requirements
------------

- Apple Silicon Mac (M1 or newer)
- macOS 14 Sonoma or newer
- No Python, Homebrew, Rosetta or developer tools

Install the graphical applications
----------------------------------

Drag PSXFoundry PSP.app and PSXFoundry PS3.app onto the Applications shortcut
in this window. The applications are ad-hoc signed and not notarized, so macOS
will block the first launch.

To approve an application:

1. Try to open it once from Applications, then dismiss the warning.
2. Open System Settings > Privacy & Security.
3. Scroll to Security and click Open Anyway for the PSXFoundry application.
4. Authenticate if macOS asks, then confirm Open.

Repeat this once for the other application. Do not disable Gatekeeper.
Apple instructions:
https://support.apple.com/guide/mac-help/open-an-app-by-overriding-security-settings-mh40617/mac

Install the command-line tool
-----------------------------

Control-click Install CLI.command and choose Open. The default destination is
~/.local/bin/psxfoundry and does not require administrator access. You can
choose another directory or run ./psxfoundry from this disk.

If ~/.local/bin is not already on PATH, add this line to ~/.zshrc:

    export PATH="$HOME/.local/bin:$PATH"

Then open a new Terminal window and run:

    psxfoundry --help

The CLI may take a few seconds to prepare its embedded runtime when it starts.
It does not install files outside the selected directory.

The bundle handles CUE/BIN, CCD/IMG, BIN/IMG, ZIP and CHD images without
external tools. PDF, ZIP and image-directory manuals are also supported.

Data and removal
----------------

Preferences: ~/Library/Application Support/PSXFoundry/
Logs:         ~/Library/Logs/PSXFoundry/
Work cache:   ~/Library/Caches/PSXFoundry/

To uninstall, remove the two applications, ~/.local/bin/psxfoundry if installed,
and the three data directories above if you no longer need their contents.

PSXFoundry does not write inside the applications or the disk image. See
THIRD_PARTY_NOTICES.md for bundled software and licenses.
