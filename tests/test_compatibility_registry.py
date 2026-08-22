import copy
import json
import tempfile
import unittest
from pathlib import Path

from psxfoundry.popfe_registry import adapt_popfe
from psxfoundry.registry import (
    CompatibilityAction,
    CompatibilityRegistry,
    CompatibilityRule,
    DiscIdentity,
    RegistryError,
    RuleMatch,
    RuleSource,
    load_registry,
    parse_catalog,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CRASH_BASH_SHA256 = "69e9d985b9d539c4b8eb514a0619993caf26332089d4ffe7d8187dc0f7893649"


def make_rule(rule_id, match):
    return CompatibilityRule(
        id=rule_id,
        title="Registry test",
        status="reported",
        match=match,
        targets=("psp",),
        actions=(CompatibilityAction("preserve_disc"),),
        sources=(RuleSource("Test", "https://example.com"),),
        credits=("Test contributor",),
        tests=(),
    )


class BundledRegistryTests(unittest.TestCase):
    def test_loads_crash_bash_assets_and_exact_revision(self):
        registry = load_registry()
        identity = DiscIdentity(
            disc_ids=("SCES02834",),
            sha256=(CRASH_BASH_SHA256,),
            region="pal",
            sector_counts=(83904,),
        )

        rule = registry.resolve(identity, "psp")

        self.assertEqual(rule.id, "crash-bash-sces02834-europe")
        self.assertEqual(
            [action.kind for action in rule.actions],
            ["apply_ppf", "set_libcrypt", "set_pops_config"],
        )

    def test_does_not_patch_unknown_crash_bash_revision(self):
        registry = load_registry()
        identity = DiscIdentity(
            disc_ids=("SCES02834",),
            sha256=("0" * 64,),
            region="pal",
            sector_counts=(83904,),
        )

        self.assertIsNone(registry.resolve(identity, "psp"))

    def test_exact_hash_precedes_serial_fallback(self):
        fallback = make_rule("serial-fallback", RuleMatch(disc_ids=("SCUS00001",)))
        exact = make_rule(
            "exact-revision",
            RuleMatch(disc_ids=("SCUS00001",), sha256=("1" * 64,)),
        )
        registry = CompatibilityRegistry((fallback, exact))

        result = registry.resolve(
            DiscIdentity(disc_ids=("SCUS00001",), sha256=("1" * 64,)),
            "psp",
        )

        self.assertEqual(result.id, "exact-revision")

    def test_rejects_duplicate_matches(self):
        first = make_rule("first-rule", RuleMatch(disc_ids=("SCUS00001",)))
        second = make_rule("second-rule", RuleMatch(disc_ids=("SCUS00001",)))

        with self.assertRaisesRegex(RegistryError, "same match"):
            CompatibilityRegistry((first, second))


class CatalogValidationTests(unittest.TestCase):
    def setUp(self):
        path = REPOSITORY_ROOT / "compatibility" / "catalog" / "psp-foundation.json"
        self.catalog = json.loads(path.read_text(encoding="utf-8"))

    def test_rejects_unknown_rule_field(self):
        data = copy.deepcopy(self.catalog)
        data["rules"][0]["unknown"] = True

        with self.assertRaisesRegex(RegistryError, "unknown fields"):
            parse_catalog(data)

    def test_rejects_unordered_actions(self):
        data = copy.deepcopy(self.catalog)
        data["rules"][0]["actions"].reverse()

        with self.assertRaisesRegex(RegistryError, "execution order"):
            parse_catalog(data)

    def test_rejects_verified_rule_without_hardware_test(self):
        data = copy.deepcopy(self.catalog)
        data["rules"][0]["status"] = "verified"

        with self.assertRaisesRegex(RegistryError, "without a passing"):
            parse_catalog(data)

    def test_rejects_invalid_hardware_test_date(self):
        data = copy.deepcopy(self.catalog)
        data["rules"][0]["tests"] = [
            {
                "target": "psp",
                "device": "PSP-3000",
                "result": "pass",
                "date": "2026-02-30",
            }
        ]

        with self.assertRaisesRegex(RegistryError, "date is invalid"):
            parse_catalog(data)

    def test_rejects_tampered_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_dir = root / "catalog"
            catalog_dir.mkdir()
            data = copy.deepcopy(self.catalog)
            action = data["rules"][0]["actions"][0]
            asset = root / action["path"]
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"tampered")
            (catalog_dir / "rules.json").write_text(
                json.dumps(data),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RegistryError, "asset hash"):
                load_registry(catalog_dir, root)


class PopfeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = adapt_popfe(REPOSITORY_ROOT)

    def test_imports_crash_bash_settings_and_credits(self):
        rule = next(
            rule
            for rule in self.result.rules
            if rule.id == "popfe-sces02834-psp"
        )

        self.assertEqual(
            [action.kind for action in rule.actions],
            ["apply_ppf", "set_libcrypt", "set_pops_config"],
        )
        self.assertTrue(any("krHACKen" in credit for credit in rule.credits))

    def test_imports_hash_specific_ppf_rules(self):
        rules = [
            rule
            for rule in self.result.rules
            if rule.match.disc_ids == ("SLUS00330",) and rule.match.md5
        ]

        self.assertEqual(len(rules), 4)
        self.assertEqual({rule.targets for rule in rules}, {("psp", "adrenaline"), ("ps3",)})

    def test_reports_missing_upstream_assets(self):
        self.assertTrue(
            any(
                issue.path == "pspconfigs/Jet Moto/SCES-00566.bin"
                for issue in self.result.issues
            )
        )

    def test_adapter_rules_have_no_silent_conflicts(self):
        registry = self.result.registry()

        self.assertEqual(len(registry.rules), len(self.result.rules))


if __name__ == "__main__":
    unittest.main()
