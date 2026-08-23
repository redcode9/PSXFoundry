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

ACTION_DETAILS = ("path", "mode", "value", "level", "version", "magic_word")

SUMMARY_ACTIONS = {
    "apply_ppf": "game patch",
    "apply_xdelta": "game patch",
    "set_libcrypt": "LibCrypt protection data",
    "set_pops_config": "POPS compatibility settings",
    "set_game_id": "compatible Game ID",
    "set_region": "video region override",
    "set_cdda": "CD audio mode",
    "set_popsloader": "POPSLoader profile",
    "set_undither": "dithering correction",
}
SUMMARY_WARNINGS = {
    "Compatibility rule status is reported": (
        "Compatibility profile has not been confirmed on hardware"
    ),
    "Skipped revision-sensitive patches without an exact source hash": (
        "Game patch was not applied because this disc revision is unknown"
    ),
}


def _source_summary(plan):
    matches = {disc.conversion.source_match for disc in plan.discs}
    if matches == {"exact"}:
        return "Exact disc revision recognized"
    if "game" in matches:
        return "Game recognized; disc revision not verified"
    return "Disc revision not recognized"


def render_workflow_summary(plan):
    """Render the automatic choices shown before conversion."""
    actions = []
    for disc in plan.discs:
        for action in disc.conversion.actions:
            label = SUMMARY_ACTIONS.get(action.kind)
            if label and label not in actions:
                actions.append(label)

    target = "PSP" if plan.target == "psp" else "PS Vita / Adrenaline"
    lines = [f"Source: {_source_summary(plan)}", f"Target: {target}"]
    setup = ", ".join(actions) if actions else "standard conversion"
    lines.append("Automatic setup: " + setup)
    if plan.warnings:
        warnings = (
            SUMMARY_WARNINGS.get(warning, warning)
            for warning in plan.warnings
        )
        lines.append("Attention: " + "; ".join(warnings))
    return "\n".join(lines)


def _action_line(action):
    detail = next(
        (action.get(name) for name in ACTION_DETAILS if action.get(name) is not None),
        None,
    )
    label = ACTION_LABELS[action.kind]
    return f"- {label}: {detail}" if detail is not None else f"- {label}"


def _append_notes(lines, plan):
    if plan.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in plan.warnings)
    if plan.assumptions:
        lines.append("Unverified:")
        lines.extend(f"- {assumption}" for assumption in plan.assumptions)


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
    lines.extend(_action_line(action) for action in plan.actions)
    _append_notes(lines, plan)
    return "\n".join(lines) + "\n"


def render_target_workflow_report(plan):
    """Render one per-disc target workflow."""
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
                f"Source match {number}: {conversion.source_match}",
                f"Profile {number}: {conversion.rule_id or 'lossless-default'}",
            )
        )
        lines.extend(_action_line(action) for action in conversion.actions)
    _append_notes(lines, plan)
    return "\n".join(lines) + "\n"
