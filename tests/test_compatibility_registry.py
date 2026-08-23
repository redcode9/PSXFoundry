import copy
import json
import tempfile
import unittest
from pathlib import Path

from psxfoundry.popfe_registry import adapt_popfe
from psxfoundry.registry import (
    CompatibilityAction,
    CompatibilityAssetError,
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
CRASH_BASH_SHA1 = "253c05e9e8dbe9251f31b3512fd251390483cb59"
LOCAL_CRASH_BASH_SHA1 = "a2b83808967d77360d42c5e5d0a805bcf96f5764"
STATIC_CRASH_BASH_BOOT = "8635e75c51dd099a2d6f22502c16e261ca4e6d350e0558ea989303c346748e6c"


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
    def test_recognizes_static_selector_by_boot_content(self):
        registry = load_registry()
        identity = DiscIdentity(
            disc_ids=("SCES02834",),
            boot_sha256=(STATIC_CRASH_BASH_BOOT,),
            region="pal",
        )

        psp = registry.resolve(identity, "psp")
        adrenaline = registry.resolve(identity, "adrenaline")

        self.assertEqual(psp.id, "crash-bash-static-selector-psp")
        self.assertEqual(psp.status, "verified")
        self.assertEqual(psp.image_state, "prepatched")
        self.assertEqual(psp.actions[-1].get("magic_word"), 0)
        self.assertEqual(psp.tests[0].device, "PSP-2000 (02g)")
        self.assertEqual(adrenaline.id, "crash-bash-static-selector-unverified")
        self.assertEqual(adrenaline.status, "reported")
        self.assertEqual(
            registry.resolve(identity, "retroarch").id,
            "crash-bash-static-selector-unverified",
        )

    def test_loads_crash_bash_assets_and_exact_revision(self):
        registry = load_registry()
        identity = DiscIdentity(
            disc_ids=("SCES02834",),
            sha1=(CRASH_BASH_SHA1,),
            region="pal",
            sector_counts=(94332,),
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
            sha1=(LOCAL_CRASH_BASH_SHA1,),
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
        self.retail_index = next(
            index
            for index, rule in enumerate(self.catalog["rules"])
            if rule["id"] == "crash-bash-sces02834-europe"
        )

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
        rule = next(
            rule
            for rule in data["rules"]
            if rule["id"] == "crash-bash-static-selector-unverified"
        )
        rule["status"] = "verified"

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
            action = data["rules"][self.retail_index]["actions"][0]
            asset = root / action["path"]
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"tampered")
            (catalog_dir / "rules.json").write_text(
                json.dumps(data),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                CompatibilityAssetError,
                "checksum does not match",
            ):
                load_registry(catalog_dir, root)

    def test_can_defer_asset_checks_until_rule_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_dir = root / "catalog"
            catalog_dir.mkdir()
            (catalog_dir / "rules.json").write_text(
                json.dumps(self.catalog),
                encoding="utf-8",
            )

            registry = load_registry(
                catalog_dir,
                root,
                verify_assets=False,
            )

            self.assertTrue(registry.rules)


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

    def test_imports_ps3_configs(self):
        rule = next(
            rule
            for rule in self.result.rules
            if rule.id == "popfe-scus94423-ps3"
        )

        config = next(
            action for action in rule.actions if action.kind == "set_pops_config"
        )
        self.assertEqual(
            config.get("path"),
            "ps3configs/Ape Escape/SCUS-94423.BIN",
        )

    def test_retroarch_uses_subchannels_without_patching_the_image(self):
        rule = next(
            rule
            for rule in self.result.rules
            if rule.id == "popfe-sces02834-retroarch"
        )

        self.assertEqual(
            [action.kind for action in rule.actions],
            ["set_libcrypt"],
        )

    def test_reports_missing_upstream_assets(self):
        self.assertTrue(
            any(
                issue.path == "pspconfigs/Jet Moto/SCES-00566.bin"
                for issue in self.result.issues
            )
        )
        rule = next(
            rule
            for rule in self.result.rules
            if rule.match.disc_ids == ("SCES00566",) and "psp" in rule.targets
        )
        self.assertTrue(
            any(
                action.get("path") == "pspconfigs/Jet Moto/SCES-00566.bin"
                for action in rule.actions
            )
        )

    def test_adapter_rules_have_no_silent_conflicts(self):
        registry = self.result.registry()

        self.assertEqual(len(registry.rules), len(self.result.rules))


if __name__ == "__main__":
    unittest.main()
