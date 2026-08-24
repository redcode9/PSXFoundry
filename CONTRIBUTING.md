# Contributing

Keep changes narrow and describe the result. Use short declarative commit
subjects. Do not add process notes to code or documentation.

## Code

- Preserve public commands, application behaviour and output formats.
- Put disc planning and validation in focused `psxfoundry` modules.
- Share desktop dialogs and repeated PSP/PS3 behaviour.
- Use descriptive names and short functions.
- Comment only constraints that the code cannot express, in English.
- Do not edit generated databases, patches or external projects unless needed.

Both applications use one window: inputs on the left, preview on the right and
output actions in the footer. Advanced settings stay closed by default.

## Compatibility data

Rules live in `compatibility/catalog` and follow
`compatibility/schema.json`. An exact content or layout hash outranks a serial.
Binary patches require an exact source hash. Referenced files must be
redistributable, remain inside the repository and include their SHA-256.

Use `verified` only after a passing test on a named device and firmware. Use
`reported` for a sourced correction awaiting a hardware pass and
`experimental` for work still under evaluation. Add the smallest correction
for the exact revision and cover its registry, planner and conversion paths.

A useful hardware report includes the target, input SHA-256, track layout,
device, firmware, emulator version and the observed result. Do not upload game
images, BIOS files, firmware or copyrighted boot files.

## Setup

Python 3.12 is the release baseline:

```sh
git clone --recursive https://github.com/redcode9/PSXFoundry.git
cd PSXFoundry
pyenv install -s 3.12.13
pyenv local 3.12.13
python -m venv .venv
.venv/bin/python -m pip install -r packaging/macos/requirements-runtime.txt
```

Source conversions also need the native helper for each selected target. The
macOS build scripts compile and bundle the locked revisions.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -v
git diff --check
packaging/macos/build-apps.sh
packaging/macos/smoke-apps.sh
tests/integration/smoke-macos-conversions.sh build/macos/dist/psxfoundry
```

Build an Apple Silicon disk image with:

```sh
git submodule update --init --recursive
packaging/macos/build-helpers.sh
release_version=1.2.3
PSXFOUNDRY_VERSION="$release_version" packaging/macos/build-apps.sh
PSXFOUNDRY_VERSION="$release_version" packaging/macos/create-dmg.sh
packaging/macos/smoke-dmg.sh "build/macos/PSXFoundry-$release_version-macOS-arm64.dmg"
```

Every packaged Mach-O must be ARM64 and free of Homebrew or build-directory
load paths. Test the downloaded candidate with Gatekeeper. Unavailable hardware
is `not tested`, never `passed`.

Do not commit build output or diagnostics. Preserve attribution and licenses.
Generic POP-FE fixes may be proposed upstream; fork identity and release work
belongs only in PSXFoundry.
