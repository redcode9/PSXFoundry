"""Build, verify, and install signed compatibility registry packs."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from psxfoundry.registry import parse_catalog, verify_rule_assets


SCHEMA_VERSION = 1
MAX_MANIFEST_SIZE = 1024 * 1024
MAX_PACK_SIZE = 256 * 1024 * 1024
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RegistryUpdateError(ValueError):
    """Raised when a registry pack is unsafe or invalid."""


@dataclass(frozen=True)
class RegistryPack:
    version: str
    files: tuple[tuple[str, int, str], ...]


def _canonical(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_path(value):
    if not isinstance(value, str) or not value:
        raise RegistryUpdateError("registry file path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RegistryUpdateError(f"unsafe registry file path: {value}")
    return path


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(version, files):
    if not VERSION_PATTERN.fullmatch(version):
        raise RegistryUpdateError("registry version is invalid")
    entries = []
    for relative, path in sorted(files.items()):
        _safe_path(relative)
        path = Path(path)
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "files": entries,
    }


def sign_manifest(manifest, private_key):
    key = ECC.import_key(private_key)
    if not key.has_private() or key.curve != "Ed25519":
        raise RegistryUpdateError("registry signing key must be private Ed25519")
    return eddsa.new(key, "rfc8032").sign(_canonical(manifest))


def _verify_signature(manifest_data, signature, public_key):
    try:
        key = ECC.import_key(public_key)
        if key.has_private() or key.curve != "Ed25519":
            raise RegistryUpdateError("registry key must be public Ed25519")
        eddsa.new(key, "rfc8032").verify(manifest_data, signature)
    except (ValueError, TypeError) as error:
        raise RegistryUpdateError("registry signature is invalid") from error


def collect_registry_files(repository_root):
    """Collect validated catalogs, schema, and referenced redistributable assets."""
    root = Path(repository_root).resolve()
    catalog_dir = root / "compatibility" / "catalog"
    files = {}
    schema = root / "compatibility" / "schema.json"
    if not schema.is_file():
        raise RegistryUpdateError("compatibility schema is missing")
    files["compatibility/schema.json"] = schema

    for catalog in sorted(catalog_dir.glob("*.json")):
        try:
            data = json.loads(catalog.read_text(encoding="utf-8"))
            rules = parse_catalog(data, str(catalog))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RegistryUpdateError(f"invalid registry catalog {catalog}") from error
        relative_catalog = catalog.resolve().relative_to(root).as_posix()
        files[relative_catalog] = catalog
        for rule in rules:
            verify_rule_assets(rule, root)
            for action in rule.actions:
                relative = action.get("path")
                if relative is None:
                    continue
                asset = (root / relative).resolve()
                if not asset.is_relative_to(root):
                    raise RegistryUpdateError("registry asset leaves the repository")
                files[PurePosixPath(relative).as_posix()] = asset
    return files


def _zip_info(name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_registry_pack(output, version, repository_root, private_key):
    """Write a deterministic signed registry ZIP file."""
    output = Path(output)
    files = collect_registry_files(repository_root)
    manifest = _manifest(version, files)
    manifest_data = _canonical(manifest)
    signature = sign_manifest(manifest, private_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=output.name + ".",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(_zip_info("manifest.json"), manifest_data)
            archive.writestr(_zip_info("manifest.sig"), signature)
            for relative, path in sorted(files.items()):
                archive.writestr(
                    _zip_info("files/" + relative),
                    Path(path).read_bytes(),
                )
        os.replace(temporary, output)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return RegistryPack(
        version,
        tuple(
            (entry["path"], entry["size"], entry["sha256"])
            for entry in manifest["files"]
        ),
    )


def _parse_manifest(data):
    try:
        manifest = json.loads(data)
    except (TypeError, json.JSONDecodeError) as error:
        raise RegistryUpdateError("registry manifest is invalid JSON") from error
    if set(manifest) != {"schema_version", "version", "files"}:
        raise RegistryUpdateError("registry manifest has invalid fields")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise RegistryUpdateError("registry manifest schema is unsupported")
    if not isinstance(manifest["version"], str) or not VERSION_PATTERN.fullmatch(
        manifest["version"]
    ):
        raise RegistryUpdateError("registry version is invalid")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise RegistryUpdateError("registry manifest has no files")

    entries = []
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise RegistryUpdateError("registry file entry is invalid")
        path = _safe_path(entry["path"]).as_posix()
        size = entry["size"]
        digest = entry["sha256"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RegistryUpdateError("registry file size is invalid")
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            raise RegistryUpdateError("registry file hash is invalid")
        entries.append((path, size, digest))
    if [entry[0] for entry in entries] != sorted(entry[0] for entry in entries):
        raise RegistryUpdateError("registry files are not sorted")
    if len({entry[0] for entry in entries}) != len(entries):
        raise RegistryUpdateError("registry manifest contains duplicate files")
    return RegistryPack(manifest["version"], tuple(entries))


def _archive_members(archive):
    members = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = _safe_path(info.filename).as_posix()
        if path in members:
            raise RegistryUpdateError("registry pack contains duplicate files")
        file_type = (info.external_attr >> 16) & 0o170000
        if file_type not in {0, 0o100000}:
            raise RegistryUpdateError("registry pack contains a non-regular file")
        if info.flag_bits & 0x1:
            raise RegistryUpdateError("encrypted registry packs are not supported")
        members[path] = info
    return members


def verify_registry_pack(pack_path, public_key):
    """Verify a complete pack without extracting it."""
    try:
        with zipfile.ZipFile(pack_path) as archive:
            members = _archive_members(archive)
            if "manifest.json" not in members or "manifest.sig" not in members:
                raise RegistryUpdateError("registry pack has no signed manifest")
            if members["manifest.json"].file_size > MAX_MANIFEST_SIZE:
                raise RegistryUpdateError("registry manifest is too large")
            if members["manifest.sig"].file_size != 64:
                raise RegistryUpdateError("registry signature has an invalid size")
            manifest_data = archive.read(members["manifest.json"])
            signature = archive.read(members["manifest.sig"])
            _verify_signature(manifest_data, signature, public_key)
            pack = _parse_manifest(manifest_data)
            expected = {"manifest.json", "manifest.sig"}
            total = 0
            for relative, size, expected_hash in pack.files:
                name = "files/" + relative
                expected.add(name)
                info = members.get(name)
                if info is None or info.file_size != size:
                    raise RegistryUpdateError(f"registry file size mismatch: {relative}")
                total += size
                if total > MAX_PACK_SIZE:
                    raise RegistryUpdateError("registry pack is too large")
                digest = hashlib.sha256()
                with archive.open(info) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != expected_hash:
                    raise RegistryUpdateError(f"registry file hash mismatch: {relative}")
            if set(members) != expected:
                raise RegistryUpdateError("registry pack contains undeclared files")
            return pack
    except zipfile.BadZipFile as error:
        raise RegistryUpdateError("registry pack is not a valid ZIP file") from error


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(data))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def verify_installed_registry(directory, public_key):
    """Verify the signed manifest and every file in an installed version."""
    directory = Path(directory).resolve()
    try:
        manifest_data = (directory / "manifest.json").read_bytes()
        signature = (directory / "manifest.sig").read_bytes()
    except OSError as error:
        raise RegistryUpdateError("installed registry has no signed manifest") from error
    if len(manifest_data) > MAX_MANIFEST_SIZE or len(signature) != 64:
        raise RegistryUpdateError("installed registry manifest is invalid")
    _verify_signature(manifest_data, signature, public_key)
    pack = _parse_manifest(manifest_data)
    expected = {"manifest.json", "manifest.sig"}
    for relative, size, expected_hash in pack.files:
        expected.add(relative)
        path = directory.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file() or path.stat().st_size != size:
            raise RegistryUpdateError(
                f"installed registry file size mismatch: {relative}"
            )
        if _sha256(path) != expected_hash:
            raise RegistryUpdateError(
                f"installed registry file hash mismatch: {relative}"
            )
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise RegistryUpdateError("installed registry contains undeclared files")
    return pack


def activate_registry_version(version, public_key, store_root):
    """Verify and activate an installed version, retaining all other versions."""
    if not VERSION_PATTERN.fullmatch(version):
        raise RegistryUpdateError("registry version is invalid")
    store_root = Path(store_root)
    directory = store_root / "versions" / version
    pack = verify_installed_registry(directory, public_key)
    if pack.version != version:
        raise RegistryUpdateError("installed registry version does not match its path")
    _atomic_json(
        store_root / "active.json",
        {"schema_version": SCHEMA_VERSION, "version": version},
    )
    return directory


def active_registry_root(store_root, public_key):
    """Return the active verified registry root, or None when none is installed."""
    store_root = Path(store_root)
    try:
        active = json.loads(
            (store_root / "active.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryUpdateError("active registry pointer is invalid") from error
    if set(active) != {"schema_version", "version"}:
        raise RegistryUpdateError("active registry pointer has invalid fields")
    if active["schema_version"] != SCHEMA_VERSION:
        raise RegistryUpdateError("active registry pointer schema is unsupported")
    version = active["version"]
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise RegistryUpdateError("active registry version is invalid")
    directory = store_root / "versions" / version
    pack = verify_installed_registry(directory, public_key)
    if pack.version != version:
        raise RegistryUpdateError("active registry version does not match its path")
    return directory


def install_registry_pack(pack_path, public_key, store_root):
    """Verify, extract, and atomically activate one registry version."""
    pack = verify_registry_pack(pack_path, public_key)
    store_root = Path(store_root)
    versions = store_root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    destination = versions / pack.version
    if destination.is_dir():
        installed = verify_installed_registry(destination, public_key)
        if installed != pack:
            raise RegistryUpdateError("installed registry version has different files")
    else:
        staging = Path(tempfile.mkdtemp(prefix=pack.version + ".", dir=versions))
        try:
            with zipfile.ZipFile(pack_path) as archive:
                manifest = archive.read("manifest.json")
                signature = archive.read("manifest.sig")
                (staging / "manifest.json").write_bytes(manifest)
                (staging / "manifest.sig").write_bytes(signature)
                for relative, _, _ in pack.files:
                    output = staging.joinpath(*PurePosixPath(relative).parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open("files/" + relative) as source:
                        with output.open("wb") as target:
                            shutil.copyfileobj(source, target, 1024 * 1024)
            installed = verify_installed_registry(staging, public_key)
            if installed != pack:
                raise RegistryUpdateError("extracted registry does not match its pack")
            os.replace(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return activate_registry_version(pack.version, public_key, store_root)


def export_public_key(private_key):
    """Return an ASCII public key suitable for the application bundle."""
    key = ECC.import_key(private_key)
    if not key.has_private() or key.curve != "Ed25519":
        raise RegistryUpdateError("registry signing key must be private Ed25519")
    return key.public_key().export_key(format="PEM").encode("ascii")
