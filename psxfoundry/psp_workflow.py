"""Prepare automatic PSP and Adrenaline conversions."""

from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
from pathlib import Path

from popfe_runtime import runtime as popfe_runtime
from psxfoundry.disc import DiscDescription, analyze_disc
from psxfoundry.planner import ConversionPlan, plan_conversion
from psxfoundry.popfe_registry import AdapterIssue, adapt_popfe
from psxfoundry.registry import (
    CompatibilityAction,
    CompatibilityRegistry,
    RegistryError,
    load_registry,
)


PSP_TARGETS = {"psp", "adrenaline"}


@dataclass(frozen=True)
class PlannedPatch:
    kind: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class PspDiscPlan:
    description: DiscDescription
    conversion: ConversionPlan
    output_disc_id: str
    patches: tuple[PlannedPatch, ...]
    config_path: Path | None
    libcrypt_magic_word: int | None
    cdda_mode: str | None
    compression_level: int
    region_override: str | None
    undither: bool
    popsloader_version: str | None


@dataclass(frozen=True)
class PspWorkflowPlan:
    target: str
    title: str
    discs: tuple[PspDiscPlan, ...]
    adapter_issues: tuple[AdapterIssue, ...] = ()

    @property
    def output_disc_ids(self):
        return tuple(disc.output_disc_id for disc in self.discs)

    @property
    def expected_decoded_sizes(self):
        return execution_decoded_sizes(self)

    @property
    def use_cdda(self):
        return any(disc.cdda_mode == "raw" for disc in self.discs)

    @property
    def compression_level(self):
        levels = {disc.compression_level for disc in self.discs}
        if len(levels) != 1:
            raise RegistryError("all discs in one EBOOT need one compression level")
        return levels.pop()

    @property
    def force_ntsc(self):
        regions = {
            disc.region_override
            for disc in self.discs
            if disc.region_override is not None
        }
        if len(regions) > 1:
            raise RegistryError("one EBOOT cannot use conflicting region overrides")
        return bool(regions and next(iter(regions)).startswith("ntsc"))

    @property
    def undither(self):
        return any(disc.undither for disc in self.discs)

    @property
    def popsloader_versions(self):
        return tuple(
            dict.fromkeys(
                disc.popsloader_version
                for disc in self.discs
                if disc.popsloader_version
            )
        )

    @property
    def warnings(self):
        warnings = [
            warning
            for disc in self.discs
            for warning in disc.conversion.warnings
        ]
        disc_ids = {disc.description.disc_id for disc in self.discs}
        warnings.extend(
            f"{issue.disc_id}: {issue.message} ({issue.path})"
            for issue in self.adapter_issues
            if issue.disc_id in disc_ids
        )
        return tuple(dict.fromkeys(warnings))

    @property
    def assumptions(self):
        return tuple(
            dict.fromkeys(
                assumption
                for disc in self.discs
                for assumption in disc.conversion.assumptions
            )
        )


def _combined_registry(resource_root):
    local = load_registry(
        Path(resource_root) / "compatibility" / "catalog",
        resource_root,
    )
    adapted = adapt_popfe(resource_root)
    local_keys = {
        (target, rule.match)
        for rule in local.rules
        for target in rule.targets
    }
    inherited = tuple(
        rule
        for rule in adapted.rules
        if not any((target, rule.match) in local_keys for target in rule.targets)
    )
    return CompatibilityRegistry(local.rules + inherited), adapted.issues


@lru_cache(maxsize=1)
def load_psp_registry():
    """Load native rules and the read-only POP-FE compatibility adapter."""
    return _combined_registry(popfe_runtime.resource_root)


def _single_action(actions, kind):
    matches = [action for action in actions if action.kind == kind]
    if len(matches) > 1:
        raise RegistryError(f"conversion plan contains repeated {kind} actions")
    return matches[0] if matches else None


def _asset_path(action, resource_root):
    if action is None:
        return None
    root = Path(resource_root).resolve()
    path = (root / action.get("path")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RegistryError(f"missing compatibility asset {action.get('path')}")
    return path


def _disc_plan(description, conversion, fallback_disc_id, resource_root):
    actions = conversion.actions
    game_id = _single_action(actions, "set_game_id")
    output_disc_id = (
        game_id.get("value")
        if game_id is not None
        else description.disc_id or fallback_disc_id
    )
    if not output_disc_id:
        raise RegistryError("could not determine a PlayStation disc ID")

    patches = tuple(
        PlannedPatch(
            action.kind,
            _asset_path(action, resource_root),
            action.get("sha256"),
        )
        for action in actions
        if action.kind in {"apply_ppf", "apply_xdelta"}
    )
    config = _single_action(actions, "set_pops_config")
    libcrypt = _single_action(actions, "set_libcrypt")
    cdda = _single_action(actions, "set_cdda")
    compression = _single_action(actions, "set_compression")
    region = _single_action(actions, "set_region")
    undither = _single_action(actions, "set_undither")
    popsloader = _single_action(actions, "set_popsloader")
    cdda_mode = cdda.get("mode") if cdda is not None else None
    return PspDiscPlan(
        description=description,
        conversion=conversion,
        output_disc_id=output_disc_id,
        patches=patches,
        config_path=_asset_path(config, resource_root),
        libcrypt_magic_word=(
            libcrypt.get("magic_word") if libcrypt is not None else None
        ),
        cdda_mode=cdda_mode,
        compression_level=(
            compression.get("level") if compression is not None else 1
        ),
        region_override=region.get("value") if region is not None else None,
        undither=(
            undither.get("enabled") if undither is not None else False
        ),
        popsloader_version=(
            popsloader.get("version") if popsloader is not None else None
        ),
    )


def build_psp_plan(
    paths,
    target="psp",
    *,
    fallback_disc_ids=(),
    registry=None,
    adapter_issues=(),
    resource_root=None,
):
    """Analyze normalized disc paths and plan each disc independently."""
    if target not in PSP_TARGETS:
        raise RegistryError(f"unsupported PSP workflow target {target}")
    paths = tuple(Path(path) for path in paths)
    if not paths:
        raise RegistryError("a PSP conversion needs at least one disc")
    fallback_disc_ids = tuple(fallback_disc_ids)
    if fallback_disc_ids and len(fallback_disc_ids) != len(paths):
        raise RegistryError("fallback disc IDs must match the disc count")

    root = Path(resource_root or popfe_runtime.resource_root)
    if registry is None:
        registry, adapter_issues = load_psp_registry()

    descriptions = []
    for number, path in enumerate(paths):
        description = analyze_disc(path)
        fallback = fallback_disc_ids[number] if fallback_disc_ids else None
        if description.disc_id is None and fallback:
            description = replace(description, disc_id=fallback)
        descriptions.append(description)

    discs = []
    for number, description in enumerate(descriptions):
        conversion = plan_conversion((description,), target, registry)
        fallback = fallback_disc_ids[number] if fallback_disc_ids else None
        discs.append(_disc_plan(description, conversion, fallback, root))

    title = next(
        (disc.description.title for disc in discs if disc.description.title),
        discs[0].description.source.stem,
    )
    return PspWorkflowPlan(
        target=target,
        title=title,
        discs=tuple(discs),
        adapter_issues=tuple(adapter_issues),
    )


def read_planned_configs(plan, *, force_ntsc=None, cdda=None):
    """Read the POPS configs and apply the selected global config bits."""
    force_ntsc = plan.force_ntsc if force_ntsc is None else force_ntsc
    cdda = plan.use_cdda if cdda is None else cdda
    configs = []
    for disc in plan.discs:
        if disc.config_path is None:
            configs.append(None)
            continue
        config = bytearray(disc.config_path.read_bytes())
        if force_ntsc:
            if len(config) > 0x0B:
                config[0x0B] |= 0x10
            if len(config) > 0x8F:
                config[0x8F] |= 0x10
        if cdda:
            if len(config) > 0x09:
                config[0x09] |= 0x20
            if len(config) > 0x8D:
                config[0x8D] |= 0x20
        configs.append(bytes(config))
    return tuple(configs)


def _decoded_source_size(disc, use_cdda):
    if use_cdda or not disc.description.has_audio:
        return disc.description.size
    data_tracks = [
        track for track in disc.description.tracks if track.mode != "AUDIO"
    ]
    if len(data_tracks) == 1:
        return (data_tracks[0].stop_sector + 1) * 2352
    return disc.description.size


def execution_decoded_sizes(plan, *, use_cdda=None):
    """Return padded decoded sizes for the effective audio mode."""
    if any(not disc.description.complete for disc in plan.discs):
        return ()
    use_cdda = plan.use_cdda if use_cdda is None else use_cdda
    block_size = 16 * 2352
    return tuple(
        (size + block_size - 1) // block_size * block_size
        for size in (
            _decoded_source_size(disc, use_cdda) for disc in plan.discs
        )
    )


def expected_decoded_hashes(plan, image_paths, *, use_cdda=None):
    """Hash the exact padded image bytes expected after conversion."""
    image_paths = tuple(Path(path) for path in image_paths)
    if len(image_paths) != len(plan.discs):
        raise ValueError("image paths must match the planned disc count")
    use_cdda = plan.use_cdda if use_cdda is None else use_cdda
    expected_sizes = execution_decoded_sizes(plan, use_cdda=use_cdda)
    if not expected_sizes:
        return ()

    hashes = []
    for disc, image_path, expected_size in zip(
        plan.discs, image_paths, expected_sizes
    ):
        digest = hashlib.sha256()
        source_size = _decoded_source_size(disc, use_cdda)
        remaining = source_size
        with image_path.open("rb") as handle:
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError(f"disc image is shorter than planned: {image_path}")
                digest.update(chunk)
                remaining -= len(chunk)
        padding = expected_size - source_size
        if padding < 0:
            raise ValueError("planned decoded size is smaller than the source data")
        zeroes = bytes(1024 * 1024)
        while padding:
            length = min(len(zeroes), padding)
            digest.update(zeroes[:length])
            padding -= length
        hashes.append(digest.hexdigest())
    return tuple(hashes)
