# Contributing

Keep changes focused. Use short commit subjects that describe the result.

## Code

- Preserve commands, application behaviour and output formats.
- Keep disc planning and validation in focused `psxfoundry` modules.
- Share repeated PSP and PS3 behaviour.
- Use clear names and functions with one purpose.
- Add short English comments only when the reason is not clear from the code.
- Do not edit generated databases, patches or external projects unless needed.

Both applications use one window: inputs on the left, preview on the right and
output actions in the footer. Advanced settings stay closed by default.

## Compatibility data

Rules live in `compatibility/catalog` and follow
`compatibility/schema.json`. An exact content or layout hash outranks a serial.
Binary patches require an exact source hash. Referenced files must be
redistributable, remain inside the repository and include their SHA-256.

Use `verified` only after a passing test on a named device and firmware. Use
`reported` for a sourced correction that still needs a hardware test. Use
`experimental` for work still under evaluation. Apply the smallest correction
to the exact revision and test the registry, planner and conversion paths.

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

Some conversion targets need native helpers. The macOS build scripts compile
and bundle the locked revisions.

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

Every packaged Mach-O must be ARM64 and must not load files from Homebrew or the
build directory. Test the downloaded candidate with Gatekeeper. Unavailable
hardware is `not tested`, never `passed`.

Do not commit build output or diagnostics. Preserve attribution and licenses.
Keep PSXFoundry branding and release work in this repository.
