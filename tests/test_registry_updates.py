import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from Crypto.PublicKey import ECC

from psxfoundry.updates import (
    RegistryUpdateError,
    activate_registry_version,
    active_registry_root,
    build_registry_pack,
    export_public_key,
    install_registry_pack,
    verify_registry_pack,
)


class RegistryUpdateTests(unittest.TestCase):
    def setUp(self):
        key = ECC.generate(curve="Ed25519")
        self.private_key = key.export_key(format="PEM").encode("ascii")
        self.public_key = export_public_key(self.private_key)

    def repository(self, root):
        catalog = root / "compatibility" / "catalog"
        catalog.mkdir(parents=True)
        (root / "compatibility" / "schema.json").write_text(
            "{}", encoding="utf-8"
        )
        asset = root / "configs" / "profile.bin"
        asset.parent.mkdir()
        asset.write_bytes(b"profile")
        import hashlib

        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        data = {
            "schema_version": 1,
            "catalog": "test",
            "rules": [
                {
                    "id": "test-game",
                    "title": "Test game",
                    "status": "reported",
                    "match": {"disc_ids": ["SCUS00001"]},
                    "targets": ["psp"],
                    "actions": [
                        {
                            "type": "set_pops_config",
                            "path": "configs/profile.bin",
                            "sha256": digest,
                        }
                    ],
                    "sources": [
                        {"name": "Test", "url": "https://example.com"}
                    ],
                    "credits": ["Test"],
                    "tests": [],
                }
            ],
        }
        (catalog / "test.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def build(self, root, version="1.0.0"):
        repository = root / "repository"
        self.repository(repository)
        output = root / f"registry-{version}.zip"
        build_registry_pack(output, version, repository, self.private_key)
        return output

    def test_builds_and_verifies_a_signed_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.build(root)
            second = root / "second.zip"
            build_registry_pack(
                second,
                "1.0.0",
                root / "repository",
                self.private_key,
            )

            pack = verify_registry_pack(first, self.public_key)

            self.assertEqual(pack.version, "1.0.0")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                [path for path, _, _ in pack.files],
                [
                    "compatibility/catalog/test.json",
                    "compatibility/schema.json",
                    "configs/profile.bin",
                ],
            )

    def test_rejects_a_tampered_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.build(root)
            tampered = root / "tampered.zip"
            with zipfile.ZipFile(original) as source:
                with zipfile.ZipFile(tampered, "w") as output:
                    for info in source.infolist():
                        data = source.read(info)
                        if info.filename == "files/configs/profile.bin":
                            data = b"changed"
                        output.writestr(info, data)

            with self.assertRaisesRegex(RegistryUpdateError, "hash mismatch"):
                verify_registry_pack(tampered, self.public_key)

    def test_rejects_a_pack_signed_by_another_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = self.build(root)
            other = ECC.generate(curve="Ed25519").public_key().export_key(
                format="PEM"
            ).encode("ascii")

            with self.assertRaisesRegex(RegistryUpdateError, "signature"):
                verify_registry_pack(pack, other)

    def test_rejects_undeclared_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.build(root)
            extra = root / "extra.zip"
            with zipfile.ZipFile(original) as source:
                with zipfile.ZipFile(extra, "w") as output:
                    for info in source.infolist():
                        output.writestr(info, source.read(info))
                    output.writestr("files/extra.txt", b"extra")

            with self.assertRaisesRegex(RegistryUpdateError, "undeclared"):
                verify_registry_pack(extra, self.public_key)

    def test_installs_new_versions_without_removing_the_previous_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.build(root, "1.0.0")
            second = root / "registry-1.1.0.zip"
            build_registry_pack(
                second,
                "1.1.0",
                root / "repository",
                self.private_key,
            )
            store = root / "store"

            install_registry_pack(first, self.public_key, store)
            active = install_registry_pack(second, self.public_key, store)

            self.assertTrue((store / "versions" / "1.0.0").is_dir())
            self.assertEqual(active.name, "1.1.0")
            self.assertEqual(
                json.loads((store / "active.json").read_text())["version"],
                "1.1.0",
            )

            restored = activate_registry_version(
                "1.0.0", self.public_key, store
            )
            self.assertEqual(restored.name, "1.0.0")
            self.assertEqual(
                json.loads((store / "active.json").read_text())["version"],
                "1.0.0",
            )
            self.assertEqual(
                active_registry_root(store, self.public_key),
                restored,
            )

    def test_refuses_to_reactivate_a_modified_installed_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = self.build(root)
            store = root / "store"
            installed = install_registry_pack(pack, self.public_key, store)
            (installed / "configs" / "profile.bin").write_bytes(b"changed")

            with self.assertRaisesRegex(RegistryUpdateError, "installed registry"):
                install_registry_pack(pack, self.public_key, store)


if __name__ == "__main__":
    unittest.main()
