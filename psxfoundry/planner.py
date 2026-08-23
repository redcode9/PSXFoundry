"""Build deterministic conversion plans from analyzed discs."""

from dataclasses import dataclass

from psxfoundry.disc import DiscDescription
from psxfoundry.psp import padded_decoded_size
from psxfoundry.registry import (
    ACTION_ORDER,
    CompatibilityAction,
    CompatibilityRegistry,
    DiscIdentity,
    RegistryError,
)


@dataclass(frozen=True)
class ConversionPlan:
    target: str
    title: str
    discs: tuple[DiscDescription, ...]
    rule_id: str | None
    rule_status: str | None
    actions: tuple[CompatibilityAction, ...]
    expected_decoded_sizes: tuple[int, ...]
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]


def _identity(discs):
    complete = all(disc.complete for disc in discs)
    disc_ids = tuple(disc.disc_id for disc in discs) if all(disc.disc_id for disc in discs) else ()
    regions = {disc.region for disc in discs}
    region = regions.pop() if len(regions) == 1 else None
    layouts = (
        tuple(disc.track_layout_sha256 for disc in discs)
        if all(disc.track_layout_sha256 for disc in discs)
        else ()
    )
    sectors = (
        tuple(disc.sector_count for disc in discs)
        if all(disc.sector_count is not None for disc in discs)
        else ()
    )
    return DiscIdentity(
        disc_ids=disc_ids,
        sha256=tuple(disc.sha256 for disc in discs) if complete else (),
        md5=tuple(disc.md5 for disc in discs) if complete else (),
        region=region,
        track_layout_sha256=layouts,
        sector_counts=sectors,
    )


def _merge_actions(rule_actions, discs, target):
    actions = [CompatibilityAction("preserve_disc")]
    actions.extend(rule_actions)
    kinds = {action.kind for action in actions}
    if any(disc.has_audio for disc in discs) and "set_cdda" not in kinds:
        actions.append(CompatibilityAction("set_cdda", (("mode", "raw"),)))
    if target in {"psp", "adrenaline"} and "set_compression" not in kinds:
        actions.append(CompatibilityAction("set_compression", (("level", 1),)))

    unique = []
    for action in actions:
        if action not in unique:
            unique.append(action)
    return tuple(sorted(unique, key=lambda action: ACTION_ORDER[action.kind]))


def plan_conversion(discs, target, registry):
    """Select one rule and add lossless defaults for uncovered inputs."""
    discs = tuple(discs)
    if not discs:
        raise RegistryError("a conversion plan needs at least one disc")
    if not isinstance(registry, CompatibilityRegistry):
        raise TypeError("registry must be a CompatibilityRegistry")

    identity = _identity(discs)
    rule = registry.resolve(identity, target)
    warnings = [warning for disc in discs for warning in disc.warnings]
    assumptions = []
    if rule is None:
        assumptions.append("No compatibility rule matches this disc revision")
    elif rule.status != "verified":
        warnings.append(f"Compatibility rule status is {rule.status}")

    rule_actions = rule.actions if rule else ()
    if rule is not None and not (rule.match.sha256 or rule.match.md5):
        skipped = tuple(
            action.kind
            for action in rule_actions
            if action.kind in {"apply_ppf", "apply_xdelta"}
        )
        if skipped:
            rule_actions = tuple(
                action
                for action in rule_actions
                if action.kind not in {"apply_ppf", "apply_xdelta"}
            )
            warnings.append(
                "Skipped revision-sensitive patches without an exact source hash"
            )
            assumptions.append(
                "A matching source hash is required before applying "
                + ", ".join(skipped)
            )

    actions = _merge_actions(rule_actions, discs, target)
    cdda = next((action for action in actions if action.kind == "set_cdda"), None)
    use_cdda = cdda is None or cdda.get("mode") != "atrac3"
    expected_sizes = tuple(
        padded_decoded_size(disc, use_cdda) for disc in discs if disc.complete
    )
    if len(expected_sizes) != len(discs):
        expected_sizes = ()

    title = next((disc.title for disc in discs if disc.title), discs[0].source.stem)
    return ConversionPlan(
        target=target,
        title=title,
        discs=discs,
        rule_id=rule.id if rule else None,
        rule_status=rule.status if rule else None,
        actions=actions,
        expected_decoded_sizes=expected_sizes,
        warnings=tuple(warnings),
        assumptions=tuple(assumptions),
    )
