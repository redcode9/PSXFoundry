<p align="center">
  <img src="packaging/assets/PSXFoundry-mark.svg" width="160" alt="PSXFoundry mark">
</p>

# PSXFoundry

PSXFoundry converts PlayStation disc images for PSP, PS Vita with Adrenaline,
PS2, PS3, PSIO, RetroArch and PlayStation Classic. It detects each disc,
selects target-specific compatibility settings and writes a report beside the
result.

This project is an independent fork of
[POP-FE](https://github.com/sahlberg/pop-fe), created by Ronnie Sahlberg and
improved by its contributors. The original macOS contribution remains in
[POP-FE pull request #305](https://github.com/sahlberg/pop-fe/pull/305).

## Features

- CUE/BIN, CCD/IMG, raw BIN or IMG, ZIP, CHD and multidisc input.
- Natural multidisc ordering and automatic game, region and track detection.
- Local artwork, manual, audio and SBI import before online lookup.
- Target-specific POPS configuration, CD audio handling and compression.
- Exact PPF or Xdelta corrections for known disc revisions.
- Structural validation and atomic output writes.

CUE is preferred because it preserves the original track layout. Unknown disc
revisions keep a conservative lossless profile and are never silently patched.

| Target | Output |
| --- | --- |
| PSP | `EBOOT.PBP` under `PSP/GAME` |
| PS Vita / Adrenaline | `EBOOT.PBP` under `pspemu/PSP/GAME` |
| PS2 | POPStarter VCD and artwork |
| PS3 | Installable PKG |
| PSIO | BIN, CU2 and multidisc list |
| RetroArch | BIN/CUE, M3U or PBP layout |
| PlayStation Classic | AutoBleem PBP layout |

## macOS

The release supports Apple Silicon and macOS 14 or newer. Download
`PSXFoundry-<version>-macOS-arm64.dmg` from
[GitHub Releases](https://github.com/redcode9/PSXFoundry/releases). It does not
require Python, Homebrew, Rosetta or Xcode.

1. Drag the applications into `Applications`.
2. Try to open an application and dismiss the warning.
3. Open **System Settings > Privacy & Security** and select **Open Anyway**.

The applications are ad-hoc signed and not notarized. Approve each one once;
do not disable Gatekeeper. The disk image also contains the CLI and a
user-local installer.

## PSP and Adrenaline

Open **PSXFoundry PSP**, select the target and import a game folder. Folder
import finds up to five discs and can include all of them or only the first. It
also looks for `ICON0.PNG`, `PIC0.PNG`, `PIC1.PNG`, preview audio, a manual,
`LOGO.PNG` and an SBI file matching the disc name or serial.

Local files take priority. Missing SBI data is downloaded from
[PSX DataCenter](https://psxdatacenter.com/sbifiles.html), checked against the
disc and cached. If no verified fix is available, PSXFoundry explains the risk
before allowing an unpatched conversion.

Compatibility rules use content and layout hashes, not filenames. A known
prepatched image keeps its existing correction. Crash Bash `SCES-02834`
includes separate profiles for the verified European retail disc and the
Static PAL/NTSC selector. The selector profile passed on a PSP-2000 (02g) with
6.61 PRO-C Infinity. Other revisions use the safe default unless their exact
hash is known.

Generated files are checked for packaging errors. Real hardware, firmware,
PopsLoader and Adrenaline can still affect compatibility.

## Command line

```sh
psxfoundry --psp-dir=/Volumes/PSP game.cue
psxfoundry --psp-dir=/Volumes/VITA/pspemu game.cue
psxfoundry --psp-dir=/Volumes/PSP --sbi game.sbi game.cue
psxfoundry --ps3-pkg=game.pkg game.cue
psxfoundry --retroarch-pbp-dir=./retroarch disc-1.cue disc-2.cue
```

Run `psxfoundry --help` for every target and override. `pop-fe` remains an alias
for existing scripts.

## Project

- [CONTRIBUTING.md](CONTRIBUTING.md) covers development and compatibility data.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) records bundled software.

Thank you to Ronnie Sahlberg and every
[POP-FE contributor](https://github.com/sahlberg/pop-fe/graphs/contributors).
Compatibility entries keep their source and contributor credits. PSXFoundry
contains no games, Sony firmware or BIOS files.

PSXFoundry is licensed under the
[GNU Lesser General Public License 2.1](LICENCE-LGPL-2.1.txt) and is not
affiliated with Sony Interactive Entertainment.
