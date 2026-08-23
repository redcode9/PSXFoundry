"""Local content-addressed cache for disc analysis."""

import hashlib
import json
from pathlib import Path, PurePosixPath

from psxfoundry.disc import DiscDescription, TrackDescription
from psxfoundry.work import atomic_write


SCHEMA_VERSION = 3


def _canonical(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _state(path):
    path = Path(path).resolve()
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "inode": stat.st_ino,
        "device": stat.st_dev,
    }


def _resolve_dependency(parent, name):
    relative = PurePosixPath(name.replace("\\", "/"))
    candidate = parent.joinpath(*relative.parts)
    if candidate.is_file():
        return candidate
    key = str(relative).casefold()
    for path in parent.rglob("*"):
        if path.is_file():
            relative_path = str(path.relative_to(parent)).replace("\\", "/")
            if relative_path.casefold() == key:
                return path
    raise FileNotFoundError(name)


def analysis_dependencies(description):
    """Return every local file needed to reproduce one description."""
    source = description.source.resolve()
    dependencies = [source]
    if description.format == "cue":
        seen = set()
        for name in description.image_sources:
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            dependencies.append(_resolve_dependency(source.parent, name).resolve())
    elif description.format == "ccd":
        dependencies.append(
            _resolve_dependency(source.parent, description.image_sources[0]).resolve()
        )
    return tuple(dict.fromkeys(dependencies))


def _serialize(description):
    return {
        "schema_version": SCHEMA_VERSION,
        "format": description.format,
        "image_sources": list(description.image_sources),
        "size": description.size,
        "sha256": description.sha256,
        "sha1": description.sha1,
        "md5": description.md5,
        "boot_path": description.boot_path,
        "boot_sha256": description.boot_sha256,
        "disc_id": description.disc_id,
        "title": description.title,
        "region": description.region,
        "sector_count": description.sector_count,
        "tracks": [
            {
                "number": track.number,
                "mode": track.mode,
                "source": track.source,
                "indexes": [list(index) for index in track.indexes],
                "start_sector": track.start_sector,
                "stop_sector": track.stop_sector,
            }
            for track in description.tracks
        ],
        "track_layout_sha256": description.track_layout_sha256,
        "protections": list(description.protections),
        "complete": description.complete,
        "warnings": list(description.warnings),
    }


def _deserialize(data, source):
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported analysis cache schema")
    required = {
        "schema_version",
        "format",
        "image_sources",
        "size",
        "sha256",
        "sha1",
        "md5",
        "boot_path",
        "boot_sha256",
        "disc_id",
        "title",
        "region",
        "sector_count",
        "tracks",
        "track_layout_sha256",
        "protections",
        "complete",
        "warnings",
    }
    if set(data) != required:
        raise ValueError("invalid analysis cache object")
    tracks = tuple(
        TrackDescription(
            number=track["number"],
            mode=track["mode"],
            source=track["source"],
            indexes=tuple(tuple(index) for index in track["indexes"]),
            start_sector=track["start_sector"],
            stop_sector=track["stop_sector"],
        )
        for track in data["tracks"]
    )
    return DiscDescription(
        source=Path(source),
        format=data["format"],
        image_sources=tuple(data["image_sources"]),
        size=data["size"],
        sha256=data["sha256"],
        sha1=data["sha1"],
        md5=data["md5"],
        boot_path=data["boot_path"],
        boot_sha256=data["boot_sha256"],
        disc_id=data["disc_id"],
        title=data["title"],
        region=data["region"],
        sector_count=data["sector_count"],
        tracks=tracks,
        track_layout_sha256=data["track_layout_sha256"],
        protections=tuple(data["protections"]),
        complete=data["complete"],
        warnings=tuple(data["warnings"]),
    )


class AnalysisCache:
    def __init__(self, root):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.index = self.root / "index"

    def _index_path(self, source):
        key = hashlib.sha256(str(Path(source).resolve()).encode("utf-8")).hexdigest()
        return self.index / (key + ".json")

    def get(self, source):
        """Return a cached description only while every dependency is unchanged."""
        source = Path(source).resolve()
        try:
            index_data = json.loads(
                self._index_path(source).read_text(encoding="utf-8")
            )
            if set(index_data) != {"schema_version", "object", "dependencies"}:
                return None
            if index_data["schema_version"] != SCHEMA_VERSION:
                return None
            if any(_state(item["path"]) != item for item in index_data["dependencies"]):
                return None
            object_digest = index_data["object"]
            object_path = self.objects / (object_digest + ".json")
            payload = object_path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != object_digest:
                return None
            return _deserialize(json.loads(payload), source)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def put(self, description):
        """Store one analysis object and its current dependency state."""
        payload = _canonical(_serialize(description))
        object_digest = hashlib.sha256(payload).hexdigest()
        object_path = self.objects / (object_digest + ".json")
        if not object_path.is_file():
            atomic_write(object_path, payload)
        index_data = {
            "schema_version": SCHEMA_VERSION,
            "object": object_digest,
            "dependencies": [
                _state(path) for path in analysis_dependencies(description)
            ],
        }
        atomic_write(self._index_path(description.source), _canonical(index_data))
        return description

    def analyze(self, source, analyzer):
        """Use a valid cached result or run and store the analyzer."""
        cached = self.get(source)
        if cached is not None:
            return cached
        return self.put(analyzer(source))
