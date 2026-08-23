"""Read current POP-FE compatibility data without changing it."""

from dataclasses import dataclass
from pathlib import Path

from psxfoundry.registry import (
    ACTION_ORDER,
    CompatibilityAction,
    CompatibilityRegistry,
    CompatibilityRule,
    RuleMatch,
    RuleSource,
    file_sha256,
)


UPSTREAM_SOURCE = RuleSource(
    "POP-FE",
    "https://github.com/sahlberg/pop-fe",
    "Imported from the current compatibility tables",
)


@dataclass(frozen=True)
class AdapterIssue:
    disc_id: str
    path: str
    message: str


@dataclass(frozen=True)
class AdapterResult:
    rules: tuple[CompatibilityRule, ...]
    issues: tuple[AdapterIssue, ...]

    def registry(self):
        return CompatibilityRegistry(self.rules)


def _asset_action(kind, relative, root, disc_id, issues):
    path = root / relative
    if not path.is_file():
        issues.append(AdapterIssue(disc_id, relative, "missing compatibility asset"))
        return CompatibilityAction(kind, (("path", relative),))
    return CompatibilityAction(
        kind,
        (("path", relative), ("sha256", file_sha256(path))),
    )


def _ordered(actions):
    unique = []
    for action in actions:
        if action is not None and action not in unique:
            unique.append(action)
    return tuple(sorted(unique, key=lambda action: ACTION_ORDER[action.kind]))


def _sources(libcrypt_entry):
    sources = [UPSTREAM_SOURCE]
    url = libcrypt_entry.get("url") if libcrypt_entry else None
    if url:
        sources.append(RuleSource("Redump", url, "LibCrypt disc reference"))
    return tuple(sources)


def _credits(libcrypt_entry):
    credits = ["POP-FE contributors"]
    credit = libcrypt_entry.get("credit") if libcrypt_entry else None
    if credit:
        credits.append(credit)
    return tuple(credits)


def _rule(
    disc_id,
    title,
    profile,
    targets,
    actions,
    libcrypt_entry,
    md5=None,
):
    suffix = f"-{md5[:8]}" if md5 else ""
    return CompatibilityRule(
        id=f"popfe-{disc_id.lower()}-{profile}{suffix}",
        title=title,
        status="reported",
        match=RuleMatch(
            disc_ids=(disc_id,),
            md5=(md5,) if md5 else (),
        ),
        targets=tuple(targets),
        actions=_ordered(actions),
        sources=_sources(libcrypt_entry),
        credits=_credits(libcrypt_entry),
        tests=(),
    )


def _patch_action(entry, root, disc_id, issues):
    if "ppf" in entry:
        return _asset_action("apply_ppf", entry["ppf"], root, disc_id, issues)
    if "xdelta" in entry:
        return _asset_action("apply_xdelta", entry["xdelta"], root, disc_id, issues)
    return None


def adapt_popfe(
    repository_root,
    games=None,
    libcrypt=None,
    ppf_fixes=None,
):
    """Return normalized rules plus missing-asset issues from POP-FE tables."""
    if games is None or libcrypt is None or ppf_fixes is None:
        from gamedb import games as current_games
        from gamedb import libcrypt as current_libcrypt
        from gamedb import ppf_fixes as current_ppf_fixes

        games = current_games if games is None else games
        libcrypt = current_libcrypt if libcrypt is None else libcrypt
        ppf_fixes = current_ppf_fixes if ppf_fixes is None else ppf_fixes

    root = Path(repository_root)
    issues = []
    rules = []
    disc_ids = sorted(set(games) | set(libcrypt) | set(ppf_fixes))

    for disc_id in disc_ids:
        game = games.get(disc_id, {})
        libcrypt_entry = libcrypt.get(disc_id, {})
        fix = ppf_fixes.get(disc_id, {})
        title = game.get("title") or fix.get("desc") or disc_id

        libcrypt_patch = None
        libcrypt_setting = None
        if libcrypt_entry:
            if "ppf" in libcrypt_entry:
                libcrypt_patch = _asset_action(
                    "apply_ppf",
                    libcrypt_entry["ppf"],
                    root,
                    disc_id,
                    issues,
                )
            libcrypt_setting = CompatibilityAction(
                "set_libcrypt",
                (("magic_word", libcrypt_entry["magic_word"]),),
            )

        pops_config = None
        if "pspconfig" in game:
            pops_config = _asset_action(
                "set_pops_config",
                game["pspconfig"],
                root,
                disc_id,
                issues,
            )

        ps3_config = None
        if "ps3config" in game:
            ps3_config = _asset_action(
                "set_pops_config",
                game["ps3config"],
                root,
                disc_id,
                issues,
            )

        cdda = None
        if game.get("psp-use-cdda"):
            cdda = CompatibilityAction("set_cdda", (("mode", "raw"),))

        tags = set(fix.get("tags", ()))
        generic_fix = _patch_action(fix, root, disc_id, issues)
        generic_on_psp = generic_fix if not tags or "psp" in tags else None
        generic_on_ps3 = generic_fix if not tags else None

        psp_actions = _ordered(
            [libcrypt_patch, generic_on_psp, libcrypt_setting, pops_config, cdda]
        )
        if psp_actions:
            rules.append(
                _rule(
                    disc_id,
                    title,
                    "psp",
                    ("psp", "adrenaline"),
                    psp_actions,
                    libcrypt_entry,
                )
            )

        ps3_actions = _ordered(
            [libcrypt_patch, generic_on_ps3, libcrypt_setting, ps3_config]
        )
        if ps3_actions:
            rules.append(
                _rule(
                    disc_id,
                    title,
                    "ps3",
                    ("ps3",),
                    ps3_actions,
                    libcrypt_entry,
                )
            )

        if libcrypt_setting is not None:
            retroarch_actions = _ordered([libcrypt_setting])
            rules.append(
                _rule(
                    disc_id,
                    title,
                    "retroarch",
                    ("retroarch",),
                    retroarch_actions,
                    libcrypt_entry,
                )
            )

        for md5, revision_fix in sorted(fix.get("hashes", {}).items()):
            revision_action = _patch_action(
                revision_fix,
                root,
                disc_id,
                issues,
            )
            if revision_action is None:
                continue
            if not tags or "psp" in tags:
                actions = _ordered(
                    [libcrypt_patch, revision_action, libcrypt_setting, pops_config, cdda]
                )
                rules.append(
                    _rule(
                        disc_id,
                        title,
                        "psp",
                        ("psp", "adrenaline"),
                        actions,
                        libcrypt_entry,
                        md5,
                    )
                )
            if not tags:
                actions = _ordered(
                    [
                        libcrypt_patch,
                        revision_action,
                        libcrypt_setting,
                        ps3_config,
                    ]
                )
                rules.append(
                    _rule(
                        disc_id,
                        title,
                        "ps3",
                        ("ps3",),
                        actions,
                        libcrypt_entry,
                        md5,
                    )
                )

    registry = CompatibilityRegistry(rules)
    return AdapterResult(registry.rules, tuple(issues))
