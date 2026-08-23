"""Versioned compatibility rules and exact-match resolution."""

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


SCHEMA_VERSION = 1
STATUSES = {"verified", "reported", "experimental"}
IMAGE_STATES = {"original", "prepatched", "modified", "unknown"}
TARGETS = {
    "psp",
    "adrenaline",
    "psio",
    "ps2",
    "ps3",
    "retroarch",
    "playstation-classic",
}
REGIONS = {"pal", "ntsc-u", "ntsc-j"}

ACTION_FIELDS = {
    "preserve_disc": (set(), set()),
    "apply_ppf": ({"path", "sha256"}, set()),
    "apply_xdelta": ({"path", "sha256"}, set()),
    "set_libcrypt": ({"magic_word"}, set()),
    "set_pops_config": ({"path", "sha256"}, set()),
    "set_game_id": ({"value"}, set()),
    "set_region": ({"value"}, set()),
    "set_cdda": ({"mode"}, set()),
    "set_compression": ({"level"}, set()),
    "set_popsloader": ({"version"}, set()),
    "set_undither": ({"enabled"}, set()),
}
ACTION_ORDER = {
    "preserve_disc": 0,
    "apply_ppf": 10,
    "apply_xdelta": 10,
    "set_libcrypt": 20,
    "set_pops_config": 30,
    "set_game_id": 40,
    "set_region": 50,
    "set_cdda": 60,
    "set_compression": 70,
    "set_popsloader": 80,
    "set_undither": 90,
}
REPEATABLE_ACTIONS = {"apply_ppf", "apply_xdelta"}

RULE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DISC_ID_PATTERN = re.compile(r"^[A-Z0-9]{4,16}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SHA1_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MD5_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class RegistryError(ValueError):
    """Raised when registry data is invalid or ambiguous."""


class CompatibilityAssetError(RegistryError):
    """Raised when a selected compatibility fix cannot be used."""

    def __init__(self, rule_id, action_kind, relative_path, reason):
        self.rule_id = rule_id
        self.action_kind = action_kind
        self.relative_path = relative_path
        self.reason = reason
        super().__init__(
            f"{rule_id} cannot use {action_kind} asset {relative_path}: {reason}"
        )

    @property
    def skipped_warning(self):
        return (
            f"Skipped {self.action_kind} asset {self.relative_path}: "
            f"{self.reason}; continued at user request"
        )


@dataclass(frozen=True)
class RuleMatch:
    disc_ids: tuple[str, ...] = ()
    sha256: tuple[str, ...] = ()
    sha1: tuple[str, ...] = ()
    md5: tuple[str, ...] = ()
    boot_sha256: tuple[str, ...] = ()
    region: str | None = None
    track_layout_sha256: tuple[str, ...] = ()
    sector_counts: tuple[int, ...] = ()

    @property
    def specificity(self):
        return (
            32 * bool(self.sha256 or self.sha1 or self.md5)
            + 24 * bool(self.boot_sha256)
            + 8 * bool(self.track_layout_sha256)
            + 4 * bool(self.sector_counts)
            + 2 * bool(self.disc_ids)
            + bool(self.region)
        )


@dataclass(frozen=True)
class CompatibilityAction:
    kind: str
    parameters: tuple[tuple[str, object], ...] = ()

    def get(self, name, default=None):
        return dict(self.parameters).get(name, default)


@dataclass(frozen=True)
class RuleSource:
    name: str
    url: str
    note: str | None = None


@dataclass(frozen=True)
class HardwareTest:
    target: str
    device: str
    result: str
    date: str
    firmware: str | None = None


@dataclass(frozen=True)
class CompatibilityRule:
    id: str
    title: str
    status: str
    match: RuleMatch
    targets: tuple[str, ...]
    actions: tuple[CompatibilityAction, ...]
    sources: tuple[RuleSource, ...]
    credits: tuple[str, ...]
    tests: tuple[HardwareTest, ...]
    image_state: str = "unknown"


@dataclass(frozen=True)
class DiscIdentity:
    disc_ids: tuple[str, ...] = ()
    sha256: tuple[str, ...] = ()
    sha1: tuple[str, ...] = ()
    md5: tuple[str, ...] = ()
    boot_sha256: tuple[str, ...] = ()
    region: str | None = None
    track_layout_sha256: tuple[str, ...] = ()
    sector_counts: tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "disc_ids", tuple(value.upper() for value in self.disc_ids))
        object.__setattr__(self, "sha256", tuple(value.lower() for value in self.sha256))
        object.__setattr__(self, "sha1", tuple(value.lower() for value in self.sha1))
        object.__setattr__(self, "md5", tuple(value.lower() for value in self.md5))
        object.__setattr__(
            self,
            "boot_sha256",
            tuple(value.lower() for value in self.boot_sha256),
        )
        if self.region is not None:
            object.__setattr__(self, "region", self.region.lower())
        object.__setattr__(
            self,
            "track_layout_sha256",
            tuple(value.lower() for value in self.track_layout_sha256),
        )


def _keys(value, required, allowed, context):
    if not isinstance(value, dict):
        raise RegistryError(f"{context} must be an object")
    missing = required - value.keys()
    unknown = value.keys() - allowed
    if missing:
        raise RegistryError(f"{context} is missing {', '.join(sorted(missing))}")
    if unknown:
        raise RegistryError(f"{context} has unknown fields: {', '.join(sorted(unknown))}")


def _string(value, context):
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{context} must be a non-empty string")
    return value


def _strings(value, context, pattern=None):
    if not isinstance(value, list) or not value:
        raise RegistryError(f"{context} must be a non-empty array")
    result = []
    for number, item in enumerate(value):
        item = _string(item, f"{context}[{number}]")
        if pattern is not None and not pattern.fullmatch(item):
            raise RegistryError(f"{context}[{number}] has an invalid value")
        result.append(item)
    return tuple(result)


def _integers(value, context):
    if not isinstance(value, list) or not value:
        raise RegistryError(f"{context} must be a non-empty array")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        raise RegistryError(f"{context} must contain positive integers")
    return tuple(value)


def _relative_path(value, context):
    value = _string(value, context)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise RegistryError(f"{context} must stay inside the repository")
    return value


def _match(data, context):
    allowed = {
        "disc_ids",
        "sha256",
        "sha1",
        "md5",
        "boot_sha256",
        "region",
        "track_layout_sha256",
        "sector_counts",
    }
    _keys(data, set(), allowed, context)
    result = RuleMatch(
        disc_ids=_strings(data["disc_ids"], f"{context}.disc_ids", DISC_ID_PATTERN)
        if "disc_ids" in data
        else (),
        sha256=_strings(data["sha256"], f"{context}.sha256", SHA256_PATTERN)
        if "sha256" in data
        else (),
        sha1=_strings(data["sha1"], f"{context}.sha1", SHA1_PATTERN)
        if "sha1" in data
        else (),
        md5=_strings(data["md5"], f"{context}.md5", MD5_PATTERN)
        if "md5" in data
        else (),
        boot_sha256=_strings(
            data["boot_sha256"],
            f"{context}.boot_sha256",
            SHA256_PATTERN,
        )
        if "boot_sha256" in data
        else (),
        region=data.get("region"),
        track_layout_sha256=_strings(
            data["track_layout_sha256"],
            f"{context}.track_layout_sha256",
            SHA256_PATTERN,
        )
        if "track_layout_sha256" in data
        else (),
        sector_counts=_integers(data["sector_counts"], f"{context}.sector_counts")
        if "sector_counts" in data
        else (),
    )
    if not any(
        (
            result.disc_ids,
            result.sha256,
            result.sha1,
            result.md5,
            result.boot_sha256,
            result.track_layout_sha256,
        )
    ):
        raise RegistryError(f"{context} needs an ID, content hash or layout hash")
    if result.region is not None and result.region not in REGIONS:
        raise RegistryError(f"{context}.region is invalid")
    lengths = [
        len(values)
        for values in (
            result.sha256,
            result.sha1,
            result.md5,
            result.boot_sha256,
            result.track_layout_sha256,
            result.sector_counts,
        )
        if values
    ]
    if result.disc_ids and any(length != len(result.disc_ids) for length in lengths):
        raise RegistryError(f"{context} disc arrays must have the same length")
    content_hashes = sum(
        bool(value) for value in (result.sha256, result.sha1, result.md5)
    )
    if content_hashes > 1:
        raise RegistryError(f"{context} must use one content hash algorithm")
    return result


def _action(data, context):
    if not isinstance(data, dict):
        raise RegistryError(f"{context} must be an object")
    kind = data.get("type")
    if kind not in ACTION_FIELDS:
        raise RegistryError(f"{context}.type is invalid")
    required, optional = ACTION_FIELDS[kind]
    _keys(data, required | {"type"}, required | optional | {"type"}, context)

    parameters = {key: value for key, value in data.items() if key != "type"}
    if "path" in parameters:
        parameters["path"] = _relative_path(parameters["path"], f"{context}.path")
    if "sha256" in parameters and not SHA256_PATTERN.fullmatch(parameters["sha256"]):
        raise RegistryError(f"{context}.sha256 is invalid")
    if kind == "set_libcrypt":
        value = parameters["magic_word"]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
            raise RegistryError(f"{context}.magic_word is invalid")
    if kind == "set_game_id" and not DISC_ID_PATTERN.fullmatch(parameters["value"]):
        raise RegistryError(f"{context}.value is not a disc ID")
    if kind == "set_region" and parameters["value"] not in REGIONS:
        raise RegistryError(f"{context}.value is not a region")
    if kind == "set_cdda" and parameters["mode"] not in {"atrac3", "raw"}:
        raise RegistryError(f"{context}.mode is invalid")
    if kind == "set_compression":
        level = parameters["level"]
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 9:
            raise RegistryError(f"{context}.level is invalid")
    if kind == "set_popsloader":
        _string(parameters["version"], f"{context}.version")
    if kind == "set_undither" and not isinstance(parameters["enabled"], bool):
        raise RegistryError(f"{context}.enabled must be a boolean")
    return CompatibilityAction(kind, tuple(sorted(parameters.items())))


def _source(data, context):
    _keys(data, {"name", "url"}, {"name", "url", "note"}, context)
    name = _string(data["name"], f"{context}.name")
    url = _string(data["url"], f"{context}.url")
    if not url.startswith(("http://", "https://")):
        raise RegistryError(f"{context}.url must use HTTP or HTTPS")
    note = data.get("note")
    if note is not None:
        note = _string(note, f"{context}.note")
    return RuleSource(name, url, note)


def _hardware_test(data, context):
    required = {"target", "device", "result", "date"}
    allowed = required | {"firmware"}
    _keys(data, required, allowed, context)
    if data["target"] not in TARGETS:
        raise RegistryError(f"{context}.target is invalid")
    if data["result"] not in {"pass", "fail", "partial"}:
        raise RegistryError(f"{context}.result is invalid")
    try:
        date.fromisoformat(data["date"])
    except (TypeError, ValueError):
        raise RegistryError(f"{context}.date is invalid")
    firmware = data.get("firmware")
    if firmware is not None:
        firmware = _string(firmware, f"{context}.firmware")
    return HardwareTest(
        data["target"],
        _string(data["device"], f"{context}.device"),
        data["result"],
        data["date"],
        firmware,
    )


def _rule(data, context):
    required = {
        "id",
        "title",
        "status",
        "match",
        "targets",
        "actions",
        "sources",
        "credits",
        "tests",
    }
    _keys(data, required, required | {"image_state"}, context)
    rule_id = _string(data["id"], f"{context}.id")
    if not RULE_ID_PATTERN.fullmatch(rule_id):
        raise RegistryError(f"{context}.id is invalid")
    if data["status"] not in STATUSES:
        raise RegistryError(f"{context}.status is invalid")
    image_state = data.get("image_state", "unknown")
    if image_state not in IMAGE_STATES:
        raise RegistryError(f"{context}.image_state is invalid")

    targets = _strings(data["targets"], f"{context}.targets")
    if len(set(targets)) != len(targets) or any(target not in TARGETS for target in targets):
        raise RegistryError(f"{context}.targets contains duplicates or invalid targets")
    if not isinstance(data["actions"], list) or not data["actions"]:
        raise RegistryError(f"{context}.actions must be a non-empty array")
    actions = tuple(
        _action(action, f"{context}.actions[{number}]")
        for number, action in enumerate(data["actions"])
    )
    order = [ACTION_ORDER[action.kind] for action in actions]
    if order != sorted(order):
        raise RegistryError(f"{context}.actions are not in execution order")
    kinds = [action.kind for action in actions if action.kind not in REPEATABLE_ACTIONS]
    if len(kinds) != len(set(kinds)):
        raise RegistryError(f"{context}.actions contains conflicting settings")

    if not isinstance(data["sources"], list) or not data["sources"]:
        raise RegistryError(f"{context}.sources must be a non-empty array")
    sources = tuple(
        _source(source, f"{context}.sources[{number}]")
        for number, source in enumerate(data["sources"])
    )
    credits = _strings(data["credits"], f"{context}.credits")
    if len(credits) != len(set(credits)):
        raise RegistryError(f"{context}.credits contains duplicates")
    if not isinstance(data["tests"], list):
        raise RegistryError(f"{context}.tests must be an array")
    tests = tuple(
        _hardware_test(test, f"{context}.tests[{number}]")
        for number, test in enumerate(data["tests"])
    )
    if any(test.target not in targets for test in tests):
        raise RegistryError(f"{context}.tests contains an undeclared target")
    if data["status"] == "verified" and not any(test.result == "pass" for test in tests):
        raise RegistryError(f"{context} is verified without a passing hardware test")

    return CompatibilityRule(
        id=rule_id,
        title=_string(data["title"], f"{context}.title"),
        status=data["status"],
        match=_match(data["match"], f"{context}.match"),
        targets=targets,
        actions=actions,
        sources=sources,
        credits=credits,
        tests=tests,
        image_state=image_state,
    )


def parse_catalog(data, source="catalog"):
    """Validate a catalog object and return immutable rules."""
    required = {"schema_version", "catalog", "rules"}
    _keys(data, required, required, source)
    if data["schema_version"] != SCHEMA_VERSION:
        raise RegistryError(f"{source} uses unsupported schema version")
    catalog = _string(data["catalog"], f"{source}.catalog")
    if not RULE_ID_PATTERN.fullmatch(catalog):
        raise RegistryError(f"{source}.catalog is invalid")
    if not isinstance(data["rules"], list):
        raise RegistryError(f"{source}.rules must be an array")
    return tuple(
        _rule(rule, f"{source}.rules[{number}]")
        for number, rule in enumerate(data["rules"])
    )


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_action_asset(rule_id, action, asset_root):
    """Return one verified action asset without allowing path traversal."""
    relative = action.get("path")
    if relative is None:
        return None

    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise RegistryError(
            f"{rule_id} asset path escapes the repository: {relative}"
        )

    root = Path(asset_root).resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise RegistryError(
            f"{rule_id} asset path escapes the repository: {relative}"
        )
    if not path.is_file():
        raise CompatibilityAssetError(
            rule_id,
            action.kind,
            relative,
            "file is missing",
        )

    expected = action.get("sha256")
    if expected is not None and file_sha256(path) != expected:
        raise CompatibilityAssetError(
            rule_id,
            action.kind,
            relative,
            "checksum does not match",
        )
    return path


def verify_rule_assets(rule, asset_root):
    """Check every referenced rule asset and its declared digest."""
    for action in rule.actions:
        resolve_action_asset(rule.id, action, asset_root)


def _matches(rule_match, identity):
    checks = (
        (rule_match.disc_ids, identity.disc_ids),
        (rule_match.sha256, identity.sha256),
        (rule_match.sha1, identity.sha1),
        (rule_match.md5, identity.md5),
        (rule_match.boot_sha256, identity.boot_sha256),
        (rule_match.track_layout_sha256, identity.track_layout_sha256),
        (rule_match.sector_counts, identity.sector_counts),
    )
    if any(expected and expected != actual for expected, actual in checks):
        return False
    if rule_match.region and rule_match.region != identity.region:
        return False
    return True


class CompatibilityRegistry:
    def __init__(self, rules):
        self.rules = tuple(rules)
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise RegistryError("registry contains duplicate rule IDs")
        matches = {}
        for rule in self.rules:
            for target in rule.targets:
                key = target, rule.match
                if key in matches:
                    raise RegistryError(
                        f"rules {matches[key]} and {rule.id} have the same match"
                    )
                matches[key] = rule.id

    def resolve(self, identity, target):
        """Return the most specific matching rule for one target."""
        if target not in TARGETS:
            raise RegistryError(f"unknown target {target}")
        candidates = [
            rule
            for rule in self.rules
            if target in rule.targets and _matches(rule.match, identity)
        ]
        if not candidates:
            return None
        specificity = max(rule.match.specificity for rule in candidates)
        winners = [
            rule for rule in candidates if rule.match.specificity == specificity
        ]
        if len(winners) != 1:
            names = ", ".join(rule.id for rule in winners)
            raise RegistryError(f"ambiguous compatibility rules: {names}")
        return winners[0]


def load_registry(catalog_dir=None, asset_root=None, *, verify_assets=True):
    """Load all local catalogs in stable filename order."""
    repository_root = Path(__file__).resolve().parents[1]
    catalog_dir = Path(catalog_dir or repository_root / "compatibility" / "catalog")
    asset_root = Path(asset_root or repository_root)
    rules = []
    for path in sorted(catalog_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RegistryError(f"cannot read {path}: {error}") from error
        catalog_rules = parse_catalog(data, str(path))
        if verify_assets:
            for rule in catalog_rules:
                verify_rule_assets(rule, asset_root)
        rules.extend(catalog_rules)
    return CompatibilityRegistry(rules)
