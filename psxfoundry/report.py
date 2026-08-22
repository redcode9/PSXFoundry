"""Short conversion reports suitable for support requests."""


ACTION_LABELS = {
    "preserve_disc": "Preserve the complete disc image",
    "apply_ppf": "Apply PPF correction",
    "apply_xdelta": "Apply Xdelta correction",
    "set_libcrypt": "Generate LibCrypt subchannel data",
    "set_pops_config": "Insert POPS configuration",
    "set_game_id": "Override Game ID",
    "set_region": "Override region",
    "set_cdda": "Select CD audio mode",
    "set_compression": "Set PSISO compression",
    "set_popsloader": "Require PopsLoader version",
    "set_undither": "Set dithering correction",
}


def render_plan_report(plan):
    """Render one immutable plan as plain text."""
    lines = [
        "PSXFoundry conversion plan",
        f"Target: {plan.target}",
        f"Game: {plan.title}",
        f"Profile: {plan.rule_id or 'lossless-default'}",
    ]
    for number, disc in enumerate(plan.discs, start=1):
        disc_id = disc.disc_id or "unknown"
        lines.append(
            f"Disc {number}: {disc_id}, {disc.format}, sha256 {disc.sha256[:12]}"
        )
    lines.append("Actions:")
    for action in plan.actions:
        detail = next(
            (
                action.get(name)
                for name in ("path", "mode", "value", "level", "version", "magic_word")
                if action.get(name) is not None
            ),
            None,
        )
        label = ACTION_LABELS[action.kind]
        lines.append(f"- {label}: {detail}" if detail is not None else f"- {label}")
    if plan.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in plan.warnings)
    if plan.assumptions:
        lines.append("Unverified:")
        lines.extend(f"- {assumption}" for assumption in plan.assumptions)
    return "\n".join(lines) + "\n"


def render_psp_workflow_report(plan):
    """Render one per-disc PSP or Adrenaline workflow."""
    lines = [
        "PSXFoundry conversion plan",
        f"Target: {plan.target}",
        f"Game: {plan.title}",
    ]
    for number, disc in enumerate(plan.discs, start=1):
        conversion = disc.conversion
        description = disc.description
        lines.extend(
            (
                f"Disc {number}: {disc.output_disc_id}, "
                f"{description.format}, sha256 {description.sha256[:12]}",
                f"Profile {number}: {conversion.rule_id or 'lossless-default'}",
            )
        )
        for action in conversion.actions:
            detail = next(
                (
                    action.get(name)
                    for name in (
                        "path",
                        "mode",
                        "value",
                        "level",
                        "version",
                        "magic_word",
                    )
                    if action.get(name) is not None
                ),
                None,
            )
            label = ACTION_LABELS[action.kind]
            lines.append(
                f"- {label}: {detail}" if detail is not None else f"- {label}"
            )
    if plan.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in plan.warnings)
    if plan.assumptions:
        lines.append("Unverified:")
        lines.extend(f"- {assumption}" for assumption in plan.assumptions)
    return "\n".join(lines) + "\n"
