# Compatibility

PSXFoundry creates target-specific outputs from one disc description. It does
not assume that settings valid for PSP are also valid for Adrenaline, PS3 or an
emulator.

## Support levels

| Status | Meaning |
| --- | --- |
| Verified | The exact rule has at least one recorded passing hardware test. |
| Reported | The correction has a credible source but still needs a recorded hardware pass. |
| Experimental | The correction is under evaluation and may change. |
| Lossless default | No exact rule matched; the original layout is preserved with safe target defaults. |

Generated PBP files are checked for their structure, offsets, disc table,
embedded configuration and payload bounds. This detects packaging errors; it
does not replace testing on real hardware.

## Modified disc images

Disc detection uses logical data sectors, the ISO 9660 file tree and the boot
executable. Its result does not depend on a `.bin`, `.cue` or `.iso` filename.
Track layout remains separate because a cooked ISO cannot retain raw sectors or
CD audio.

An exact catalog match can identify an original or prepatched revision and
select its complete target profile. A known prepatched revision is preserved
without adding corrections that its patch replaces. A confirmed but unknown
modification receives no revision-sensitive binary patch; validated LibCrypt
data remains enabled unless an exact signature confirms a protection bypass.
If the available evidence cannot establish a modification, the lossless
default is used instead of guessing.

Detection records the content hash, boot path, boot executable hash and matched
signatures. Only exact evidence changes compatibility settings. Heuristic
findings are reported but do not disable required protection data.

## Target notes

- **PSP:** standard Sony POPS output. Device firmware and model can affect a
  title even when its PBP is valid.
- **PS Vita / Adrenaline:** planned separately from PSP and installed below the
  `pspemu` root. Adrenaline version and Vita firmware belong in test reports.
- **PS2:** produces the POPStarter USB layout. POPStarter and OPL are not
  included.
- **PS3:** supports CFW or HEN package installation. Emulator configuration is
  selected per disc when a known profile exists.
- **PSIO:** preserves disc order and produces CU2 metadata. Firmware is not
  included.
- **RetroArch:** keeps LibCrypt subchannel data instead of altering the image
  when the selected layout supports it. Behaviour still depends on the core.
- **PlayStation Classic:** produces an AutoBleem layout. The stock emulator has
  stricter multidisc limits than RetroArch.

## Crash Bash SCES-02834

The catalog contains a `reported` rule for the European retail revision
identified by SHA-1 and sector count, not just by `SCES-02834`. For PSP and
Adrenaline it applies the matching binary patch and POPS configuration. Exact
LibCrypt records come from a validated local, cached or downloaded SBI file.

PSXFoundry does not copy a boot file from Spyro or any other game. Substituting
copyrighted files from another title is not a safe or redistributable fix. For
an unknown revision, PSXFoundry still validates SBI data for the serial, keeps
the POPS setup, skips the binary patch and warns the user.

## Reporting a result

Attach the generated conversion report and include:

- target and output type;
- disc ID and full input SHA-256;
- dump format and track layout;
- device model, system firmware and emulator or Adrenaline version;
- whether the title booted, loaded gameplay, played CD audio and changed discs;
- a short reproduction sequence for a failure.

Do not upload game images, BIOS files, firmware or copyrighted boot files. A
hash and concise observation are enough to identify a revision.

## Rule policy

Catalogs live in `compatibility/catalog` and follow
`compatibility/schema.json`. Content and layout hashes outrank a serial match;
multidisc arrays must describe the discs in order. A binary patch requires an
exact source hash.

Rules may preserve a disc, apply a PPF or Xdelta file, require LibCrypt data,
insert a POPS configuration, override game ID or region, select audio and
compression, require a PopsLoader version, or set undithering. Referenced files
must be redistributable, stay inside the repository and include their SHA-256.

Each rule needs a stable ID, target list, ordered actions, direct sources,
credits and any hardware results. `verified` requires a passing test on a named
device and firmware. Add the smallest correction that fixes an exact revision,
then cover registry, planner and conversion behaviour with tests.

Catalog releases are deterministic signed archives. Paths, sizes, hashes and
the signature are checked before a version is activated.
