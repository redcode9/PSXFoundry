# Contributing

Keep changes narrow and explain the observable result. Commit subjects should
be short, declarative and free of process commentary.

## Setup

Clone submodules and use an isolated Python environment. Python 3.12 is the
release baseline; pyenv works well:

```sh
git clone --recursive https://github.com/redcode9/PSXFoundry.git
cd PSXFoundry
pyenv install -s 3.12.13
pyenv local 3.12.13
python -m venv .venv
.venv/bin/python -m pip install -r packaging/macos/requirements-runtime.txt
```

Source conversions also need the native helpers required by their selected
targets: ATRACDENC, Xdelta3, CHDMan, LibCrypt Patcher, PSX-Undither, Cue2cu2,
binmerge and PSL1GHT ps3py. Tk, a C/C++ toolchain, CMake, libsndfile and FFmpeg
are needed to build them. `pop-fe.py --install` retains the upstream bootstrap;
run it only in a disposable clone and virtual environment.

## Checks

Run before opening a pull request:

```sh
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Changes to macOS packaging must also pass:

```sh
packaging/macos/build-apps.sh
packaging/macos/smoke-apps.sh
tests/integration/smoke-macos-conversions.sh build/macos/dist/psxfoundry
```

Build the Apple Silicon release with the locked Python 3.12.13 interpreter and
native helpers:

```sh
git submodule update --init --recursive
packaging/macos/build-helpers.sh
PSXFOUNDRY_VERSION=0.1.0 packaging/macos/build-apps.sh
PSXFOUNDRY_VERSION=0.1.0 packaging/macos/create-dmg.sh
packaging/macos/smoke-dmg.sh build/macos/PSXFoundry-0.1.0-macOS-arm64.dmg
```

Every packaged Mach-O must be ARM64, target macOS 14 or older, and contain no
Homebrew or build-directory load path. Test Gatekeeper using the downloaded
candidate. Unavailable hardware is `not tested`, never `passed`.

## Pull requests

- Do not add games, BIOS files, Sony firmware or files copied from another game.
- Do not mark compatibility as verified without a recorded hardware pass.
- Include exact hashes for every revision-specific patch or configuration.
- Preserve attribution and third-party license notices.
- Update user documentation only when behaviour changed.
- Keep generated build output and local diagnostics out of Git.

Generic POP-FE fixes may also belong upstream. Fork-specific identity,
compatibility policy and release work should target PSXFoundry.

`popstation.py` creates or inspects PBP files; `vmp.py` converts signed PSP VMP
memory cards. Run either tool with `--help`. The Dockerfile exposes the source
CLI for platforms without a maintained binary release.
