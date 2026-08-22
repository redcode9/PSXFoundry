"""Validate generated packages against conversion expectations."""

from dataclasses import dataclass
from pathlib import Path

from psxfoundry.pbp import PbpFormatError, PbpInspection, inspect_pbp


@dataclass(frozen=True)
class EbootExpectation:
    disc_ids: tuple[str, ...] = ()
    decoded_sizes: tuple[int, ...] = ()
    decoded_sha256: tuple[str, ...] = ()
    tocs: tuple[bytes | None, ...] = ()
    configs: tuple[bytes | None, ...] = ()
    subchannel_records: tuple[int | None, ...] = ()
    require_block_checksums: bool = True


@dataclass(frozen=True)
class ValidationResult:
    inspection: PbpInspection | None
    errors: tuple[str, ...]

    @property
    def ok(self):
        return not self.errors

    def to_text(self):
        lines = ["Validation: passed" if self.ok else "Validation: failed"]
        lines.extend(f"- {error}" for error in self.errors)
        return "\n".join(lines) + "\n"


def _compare_sequence(label, actual, expected, errors):
    if expected and len(actual) != len(expected):
        errors.append(f"{label}: expected {len(expected)} entries, found {len(actual)}")
        return False
    return True


def validate_eboot(path, expectation=None):
    """Return structural and plan validation results for an EBOOT."""
    expectation = expectation or EbootExpectation()
    try:
        inspection = inspect_pbp(path)
    except (OSError, PbpFormatError) as error:
        return ValidationResult(None, (str(error),))

    errors = []
    discs = inspection.discs

    if expectation.require_block_checksums:
        for disc in discs:
            if disc.verified_block_checksums != len(disc.blocks):
                errors.append(f"disc {disc.number} has blocks without checksums")

    actual_ids = tuple(disc.disc_id for disc in discs)
    if _compare_sequence("disc IDs", actual_ids, expectation.disc_ids, errors):
        for number, (actual, expected) in enumerate(
            zip(actual_ids, expectation.disc_ids), start=1
        ):
            if actual != expected:
                errors.append(f"disc {number} ID: expected {expected}, found {actual}")

    actual_sizes = tuple(disc.decoded_size for disc in discs)
    if _compare_sequence("decoded sizes", actual_sizes, expectation.decoded_sizes, errors):
        for number, (actual, expected) in enumerate(
            zip(actual_sizes, expectation.decoded_sizes), start=1
        ):
            if actual != expected:
                errors.append(
                    f"disc {number} size: expected {expected} bytes, found {actual}"
                )

    actual_hashes = tuple(disc.decoded_sha256 for disc in discs)
    if _compare_sequence("decoded hashes", actual_hashes, expectation.decoded_sha256, errors):
        for number, (actual, expected) in enumerate(
            zip(actual_hashes, expectation.decoded_sha256), start=1
        ):
            if actual.lower() != expected.lower():
                errors.append(f"disc {number} decoded hash does not match")

    if _compare_sequence("TOCs", discs, expectation.tocs, errors):
        for number, (disc, expected) in enumerate(
            zip(discs, expectation.tocs), start=1
        ):
            if expected is not None and disc.toc != expected:
                errors.append(f"disc {number} TOC does not match")

    if _compare_sequence("configs", discs, expectation.configs, errors):
        for number, (disc, expected) in enumerate(
            zip(discs, expectation.configs), start=1
        ):
            if expected is not None and not disc.config_area.startswith(expected):
                errors.append(f"disc {number} POPS config does not match")

    if _compare_sequence(
        "subchannel records", discs, expectation.subchannel_records, errors
    ):
        for number, (disc, expected) in enumerate(
            zip(discs, expectation.subchannel_records), start=1
        ):
            if expected is not None and disc.subchannel_records != expected:
                errors.append(
                    f"disc {number} subchannel records: expected {expected}, "
                    f"found {disc.subchannel_records}"
                )

    return ValidationResult(inspection, tuple(errors))


def validate_generated_eboot(
    path,
    expectation=None,
    report_path=None,
    remove_invalid=True,
):
    """Validate a generated EBOOT and remove only that output when invalid."""
    path = Path(path)
    result = validate_eboot(path, expectation)
    if report_path is None:
        report_path = path.with_suffix(path.suffix + ".validation.txt")
    Path(report_path).write_text(result.to_text(), encoding="utf-8")
    if not result.ok and remove_invalid:
        path.unlink(missing_ok=True)
    return result
