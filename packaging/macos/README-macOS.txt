PSXFoundry for macOS (Apple Silicon)
=====================================

Requirements
------------

- Apple Silicon Mac (M1 or newer)
- macOS 14 Sonoma or newer
- No Python, Homebrew, Rosetta, or developer tools are required

Install the graphical applications
----------------------------------

Drag PSXFoundry PSP.app and PSXFoundry PS3.app onto the Applications shortcut
in this window. PSXFoundry is distributed outside the Mac App Store with an ad-hoc
signature and is not notarized, so macOS will block its first launch.

To approve an application:

1. Try to open it once from Applications, then dismiss the warning.
2. Open System Settings > Privacy & Security.
3. Scroll to Security and click Open Anyway for the PSXFoundry application.
4. Authenticate if macOS asks, then confirm Open.

Repeat this once for the other PSXFoundry application. Do not disable Gatekeeper.
Apple notes that Open Anyway is available for about one hour after the blocked
launch attempt:
https://support.apple.com/guide/mac-help/open-an-app-by-overriding-security-settings-mh40617/mac

Install the command-line tool
-----------------------------

Control-click Install CLI.command and choose Open. The default destination is
~/.local/bin/psxfoundry and does not require administrator access. You can choose
another directory when prompted, or run ./psxfoundry directly from this disk.

If ~/.local/bin is not already on PATH, add this line to ~/.zshrc:

    export PATH="$HOME/.local/bin:$PATH"

Then open a new Terminal window and run:

    psxfoundry --help

The single-file CLI may take several seconds to prepare its embedded runtime
when it starts. No files are installed globally and no network access is used
for this preparation.

The bundle handles CUE/BIN, CCD/IMG, BIN/IMG, ZIP, and CHD game images without
external tools. PDF, ZIP, and image-directory manuals are self-contained. CBR
manual extraction has the same optional external UNRAR requirement as the
existing desktop builds.

Data and removal
----------------

Preferences: ~/Library/Application Support/PSXFoundry/
Logs:         ~/Library/Logs/PSXFoundry/
Work cache:   ~/Library/Caches/PSXFoundry/

To uninstall, remove the two applications, ~/.local/bin/psxfoundry if installed,
and the three data directories above if you no longer need their contents.

PSXFoundry never requires writing inside an application bundle or this disk image.
See THIRD_PARTY_NOTICES.md for bundled software and licensing information.
