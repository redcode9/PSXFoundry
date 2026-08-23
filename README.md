<p align="center">
  <img src="packaging/assets/PSXFoundry-mark.svg" width="160" alt="PSXFoundry mark">
</p>

# PSXFoundry

PSXFoundry converts PlayStation disc images for PSP, PS Vita with Adrenaline,
PS2, PS3, PSIO, RetroArch and PlayStation Classic. It identifies each disc,
chooses target-specific compatibility settings, keeps every target isolated and
writes a conversion report beside the result.

PSXFoundry is an independent fork of
[POP-FE](https://github.com/sahlberg/pop-fe). It exists because of Ronnie
Sahlberg's original work and the contributions made by the POP-FE community.
The macOS work first developed for upstream remains available in
[POP-FE pull request #305](https://github.com/sahlberg/pop-fe/pull/305).

## What it automates

- Disc discovery and natural multidisc ordering.
- Game ID, title, region, track layout and content hash detection.
- Local artwork, manual and audio import before online lookup of missing items.
- LibCrypt handling, POPS configuration, CD audio mode and compression choice.
- Exact PPF or Xdelta corrections for known disc revisions.
- Atomic output writes and structural validation of generated PBP files.

Unknown revisions use a conservative lossless profile. A known serial alone is
not enough to apply a revision-specific binary patch.

## Targets

| Target | Output |
| --- | --- |
| PSP | `EBOOT.PBP` under `PSP/GAME` |
| PS Vita / Adrenaline | `EBOOT.PBP` under `pspemu/PSP/GAME` |
| PS2 | POPStarter VCD and artwork |
| PS3 | Installable PKG |
| PSIO | BIN, CU2 and multidisc list |
| RetroArch | BIN/CUE, M3U or PBP layouts |
| PlayStation Classic | AutoBleem PBP layout |

Inputs may be CUE/BIN, CCD/IMG, raw BIN or IMG, ZIP, CHD and multidisc sets.
CUE is preferred because it preserves the original track layout.

## macOS quick start

The prebuilt release supports Apple Silicon and macOS 14 or newer. Download
`PSXFoundry-<version>-macOS-arm64.dmg` from
[GitHub Releases](https://github.com/redcode9/PSXFoundry/releases). No Python,
Homebrew, Rosetta or Xcode installation is required.

1. Drag the applications into `Applications`.
2. Try to open an application once and dismiss the macOS warning.
3. Open **System Settings > Privacy & Security** and choose **Open Anyway**.
4. Open **PSXFoundry PSP**, select PSP or Adrenaline, then import a game folder.

The release is ad-hoc signed and not notarized. Approve each application once;
do not disable Gatekeeper. The disk image also contains the CLI and its
user-local installer.

## Folder import

The PSP application scans the selected folder without changing the source
files. **Import all discs** is enabled by default and can be turned off. It
loads up to five discs and first looks for these local assets:

- `ICON0.PNG`, `PIC0.PNG` and `PIC1.PNG`;
- `SND0.AT3` or a supported WAV file;
- `MANUAL.PDF`, `MANUAL.ZIP`, `MANUAL.CBR` or `LOGO.PNG`.

Only missing metadata and artwork are requested online. Local files always win.
Advanced overrides remain available, but normal conversions do not require
manual compatibility choices.

## Command line

The CLI can build several targets in one run:

```sh
psxfoundry --psp-dir=/Volumes/PSP game.cue
psxfoundry --psp-dir=/Volumes/VITA/pspemu game.cue
psxfoundry --ps3-pkg=game.pkg game.cue
psxfoundry --retroarch-pbp-dir=./retroarch game-disc-1.cue game-disc-2.cue
```

Use `psxfoundry --help` for every target and override. The legacy `pop-fe`
command remains an alias for scripts that already use it.

## Compatibility policy

Automation does not make a universal hardware guarantee. Rules marked
`verified` require a recorded device test; `reported` and `experimental` rules
are shown as such. Unknown or mismatched revisions are never silently patched.
Read [COMPATIBILITY.md](COMPATIBILITY.md) before reporting a title-specific
problem.

## Development

- [COMPATIBILITY.md](COMPATIBILITY.md) — support levels and rule policy.
- [CONTRIBUTING.md](CONTRIBUTING.md) — build, test and submit changes.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — bundled software licenses.

## Credits

PSXFoundry is maintained at
[redcode9/PSXFoundry](https://github.com/redcode9/PSXFoundry). The original
architecture, platform support, databases, patches and most conversion code
come from POP-FE. Thank you to Ronnie Sahlberg and every
[POP-FE contributor](https://github.com/sahlberg/pop-fe/graphs/contributors).

Compatibility entries retain their sources and contributor credits. Exact
third-party revisions and licenses are recorded in the notices and the macOS
dependency lock.

Use only disc images and firmware files that you are legally allowed to use.
PSXFoundry includes no games, Sony firmware or BIOS files.

PSXFoundry is distributed under the
[GNU Lesser General Public License 2.1](LICENCE-LGPL-2.1.txt).
It is not affiliated with or endorsed by Sony Interactive Entertainment.
