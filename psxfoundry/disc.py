"""Read disc inputs into stable, target-independent descriptions."""

from dataclasses import dataclass, replace
import configparser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


SUPPORTED_SUFFIXES = {".cue", ".ccd", ".bin", ".img", ".iso", ".chd", ".zip"}
SERIAL_PATTERN = re.compile(
    rb"(SCES|SCUS|SCPS|SLES|SLUS|SLPS|SIPS|SLED|SCED|PBPX|PCPX|SLPM|SCZS)"
    rb"[_-]?(\d{3})[._-]?(\d{2})",
    re.IGNORECASE,
)
FILE_PATTERN = re.compile(
    r"^FILE\s+(?:\"([^\"]+)\"|(.+?))\s+(?:BINARY|MOTOROLA|WAVE|AIFF|MP3)$",
    re.IGNORECASE,
)
TRACK_PATTERN = re.compile(r"^TRACK\s+(\d+)\s+(\S+)$", re.IGNORECASE)
INDEX_PATTERN = re.compile(r"^INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)$", re.IGNORECASE)


class DiscAnalysisError(ValueError):
    """Raised when an input cannot be described safely."""


@dataclass(frozen=True)
class TrackDescription:
    number: int
    mode: str
    source: str
    indexes: tuple[tuple[int, int], ...]
    start_sector: int
    stop_sector: int

    @property
    def sector_count(self):
        return self.stop_sector - self.start_sector + 1


@dataclass(frozen=True)
class DiscDescription:
    source: Path
    format: str
    image_sources: tuple[str, ...]
    size: int
    sha256: str
    sha1: str
    md5: str
    boot_path: str | None
    boot_sha256: str | None
    disc_id: str | None
    title: str | None
    region: str | None
    sector_count: int | None
    tracks: tuple[TrackDescription, ...]
    track_layout_sha256: str | None
    protections: tuple[str, ...]
    complete: bool
    warnings: tuple[str, ...]

    @property
    def has_audio(self):
        return any(track.mode == "AUDIO" for track in self.tracks)


@dataclass(frozen=True)
class DiscSet:
    title: str
    discs: tuple[DiscDescription, ...]


def _sector_size(mode):
    if mode == "MODE2/2336":
        return 2336
    if mode in {"MODE1/2048", "MODE2/2048"}:
        return 2048
    return 2352


def _user_data_offset(mode):
    if mode == "MODE1/2352":
        return 16
    if mode == "MODE2/2352":
        return 24
    if mode == "MODE2/2336":
        return 8
    return 0


class _LogicalDataTrack:
    def __init__(self, stream, mode, start_sector, sector_count):
        self.stream = stream
        self.sector_size = _sector_size(mode)
        self.data_offset = _user_data_offset(mode)
        self.start_sector = start_sector
        self.sector_count = sector_count

    def read(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.sector_count * 2048:
            raise DiscAnalysisError("ISO extent leaves the data track")
        result = bytearray()
        while size:
            sector, within = divmod(offset, 2048)
            length = min(size, 2048 - within)
            physical = (
                (self.start_sector + sector) * self.sector_size
                + self.data_offset
                + within
            )
            self.stream.seek(physical)
            chunk = self.stream.read(length)
            if len(chunk) != length:
                raise DiscAnalysisError("disc image ends inside an ISO extent")
            result.extend(chunk)
            offset += length
            size -= length
        return bytes(result)

    def block(self, number):
        return self.read(number * 2048, 2048)


def _iso_name(value):
    return value.decode("ascii", errors="replace").split(";", 1)[0].casefold()


def _directory_entries(track, extent, size):
    data = track.read(extent * 2048, size)
    position = 0
    while position < len(data):
        length = data[position]
        if length == 0:
            position = ((position // 2048) + 1) * 2048
            continue
        record = data[position : position + length]
        if len(record) != length or length < 34:
            raise DiscAnalysisError("invalid ISO 9660 directory record")
        name_length = record[32]
        name = record[33 : 33 + name_length]
        if name not in {b"\x00", b"\x01"}:
            yield (
                _iso_name(name),
                int.from_bytes(record[2:6], "little"),
                int.from_bytes(record[10:14], "little"),
                bool(record[25] & 0x02),
            )
        position += length


def _iso_entry(track, root, path):
    components = [part for part in re.split(r"[\\/]", path) if part]
    extent, size = root
    is_directory = True
    for position, component in enumerate(components):
        expected = component.split(";", 1)[0].casefold()
        entry = next(
            (
                item
                for item in _directory_entries(track, extent, size)
                if item[0] == expected
            ),
            None,
        )
        if entry is None:
            raise DiscAnalysisError(f"ISO 9660 file is missing: {path}")
        _, extent, size, is_directory = entry
        if position < len(components) - 1 and not is_directory:
            raise DiscAnalysisError(f"ISO 9660 path is not a directory: {path}")
    return extent, size, is_directory


def _iso_file(track, root, path):
    extent, size, is_directory = _iso_entry(track, root, path)
    if is_directory:
        raise DiscAnalysisError(f"ISO 9660 path is a directory: {path}")
    return track.read(extent * 2048, size)


def _boot_fingerprint(path, mode, start_sector, sector_count):
    try:
        with path.open("rb") as stream:
            track = _LogicalDataTrack(stream, mode, start_sector, sector_count)
            descriptor = track.block(16)
            if descriptor[:7] != b"\x01CD001\x01":
                return None, None, None
            root_record = descriptor[156 : 156 + descriptor[156]]
            if len(root_record) < 34:
                return None, None, None
            root = (
                int.from_bytes(root_record[2:6], "little"),
                int.from_bytes(root_record[10:14], "little"),
            )
            try:
                system = _iso_file(track, root, "SYSTEM.CNF").decode(
                    "ascii", errors="replace"
                )
                match = re.search(
                    r"BOOT\s*=\s*cdrom:\s*[\\/]?([^;\r\n]+)",
                    system,
                    re.IGNORECASE,
                )
                boot_path = match.group(1).strip() if match else "PSX.EXE"
            except DiscAnalysisError:
                boot_path = "PSX.EXE"
            extent, size, is_directory = _iso_entry(track, root, boot_path)
            if is_directory:
                return None, None, None
            digest = hashlib.sha256()
            offset = extent * 2048
            while size:
                length = min(size, 1024 * 1024)
                digest.update(track.read(offset, length))
                offset += length
                size -= length
    except (OSError, DiscAnalysisError):
        return None, None, None
    disc_id = _serial_from_bytes(boot_path.encode("ascii", errors="ignore"))
    return boot_path.replace("\\", "/"), digest.hexdigest(), disc_id


def detect_sector_mode(path):
    """Return the sector layout identified from the ISO 9660 descriptor."""
    path = Path(path)
    size = path.stat().st_size
    candidates = (
        ("MODE2/2352", 2352, 24),
        ("MODE1/2352", 2352, 16),
        ("MODE2/2048", 2048, 0),
    )
    with path.open("rb") as stream:
        for mode, sector_size, data_offset in candidates:
            if size == 0 or size % sector_size:
                continue
            stream.seek(16 * sector_size + data_offset)
            if stream.read(7) == b"\x01CD001\x01":
                return mode
    return None


def _parse_cue_text(text):
    tracks = []
    current_file = None
    current_track = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.upper().startswith(("REM ", "CATALOG ", "TITLE ", "PERFORMER ")):
            continue
        match = FILE_PATTERN.match(line)
        if match:
            current_file = match.group(1) or match.group(2)
            continue
        match = TRACK_PATTERN.match(line)
        if match:
            if current_file is None:
                raise DiscAnalysisError(f"CUE line {line_number}: TRACK has no FILE")
            current_track = {
                "number": int(match.group(1)),
                "mode": match.group(2).upper(),
                "source": current_file,
                "indexes": [],
            }
            tracks.append(current_track)
            continue
        match = INDEX_PATTERN.match(line)
        if match:
            if current_track is None:
                raise DiscAnalysisError(f"CUE line {line_number}: INDEX has no TRACK")
            minute, second, frame = map(int, match.groups()[1:])
            if second >= 60 or frame >= 75:
                raise DiscAnalysisError(f"CUE line {line_number}: invalid INDEX time")
            sector = (minute * 60 + second) * 75 + frame
            current_track["indexes"].append((int(match.group(1)), sector))

    if not tracks:
        raise DiscAnalysisError("CUE contains no tracks")
    numbers = [track["number"] for track in tracks]
    if numbers != list(range(1, len(tracks) + 1)):
        raise DiscAnalysisError("CUE track numbers are not consecutive")
    if any(not track["indexes"] for track in tracks):
        raise DiscAnalysisError("CUE track has no index")
    return tracks


def _serial_from_bytes(data, current=None):
    if current is not None:
        return current
    match = SERIAL_PATTERN.search(data)
    if not match:
        return None
    prefix, first, second = (part.decode("ascii").upper() for part in match.groups())
    return prefix + first + second


def _hash_streams(streams):
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1()
    md5 = hashlib.md5()
    size = 0
    serial = None
    overlap = b""
    for stream in streams:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            sha256.update(chunk)
            sha1.update(chunk)
            md5.update(chunk)
            size += len(chunk)
            serial = _serial_from_bytes(overlap + chunk, serial)
            overlap = chunk[-64:]
    return size, sha256.hexdigest(), sha1.hexdigest(), md5.hexdigest(), serial


def _region(disc_id):
    if disc_id is None:
        return None
    if disc_id.startswith(("SCES", "SLES", "SCED", "SLED")):
        return "pal"
    if disc_id.startswith(("SCUS", "SLUS")):
        return "ntsc-u"
    if disc_id.startswith(("SCPS", "SLPS", "SLPM", "SIPS", "SCZS")):
        return "ntsc-j"
    return None


def _metadata(disc_id):
    if disc_id is None:
        return None, ()
    try:
        from gamedb import games, libcrypt
    except ImportError:
        return None, ()
    title = games.get(disc_id, {}).get("title")
    protections = ("libcrypt",) if disc_id in libcrypt else ()
    return title, protections


def _layout(tracks):
    payload = [
        {
            "number": track.number,
            "mode": track.mode,
            "source": PurePosixPath(track.source).name.lower(),
            "indexes": track.indexes,
            "start": track.start_sector,
            "stop": track.stop_sector,
        }
        for track in tracks
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finish_tracks(parsed_tracks, sizes):
    descriptions = []
    for position, track in enumerate(parsed_tracks):
        source = track["source"]
        indexes = tuple(sorted(track["indexes"]))
        index_map = dict(indexes)
        start = index_map.get(1, indexes[0][1])
        stop = None
        for later in parsed_tracks[position + 1 :]:
            if later["source"].lower() != source.lower():
                continue
            later_indexes = dict(later["indexes"])
            stop = later_indexes.get(0, later_indexes.get(1)) - 1
            break
        if stop is None:
            stop = sizes[source.lower()] // _sector_size(track["mode"]) - 1
        if stop < start:
            raise DiscAnalysisError(f"track {track['number']} has an invalid extent")
        descriptions.append(
            TrackDescription(
                track["number"],
                track["mode"],
                source,
                indexes,
                start,
                stop,
            )
        )
    return tuple(descriptions)


def _description(
    source,
    format_name,
    image_sources,
    streams,
    parsed_tracks,
    sizes,
    source_paths=None,
):
    size, sha256, sha1, md5, disc_id = _hash_streams(streams)
    tracks = _finish_tracks(parsed_tracks, sizes)
    boot_path = None
    boot_sha256 = None
    if source_paths:
        data_track = next(
            (
                (parsed, description)
                for parsed, description in zip(parsed_tracks, tracks)
                if parsed["mode"] != "AUDIO"
            ),
            None,
        )
        if data_track is not None:
            parsed, description = data_track
            image_path = source_paths.get(parsed["source"].lower())
            if image_path is not None:
                boot_path, boot_sha256, boot_disc_id = _boot_fingerprint(
                    image_path,
                    parsed["mode"],
                    description.start_sector,
                    description.sector_count,
                )
                disc_id = boot_disc_id or disc_id
    title, protections = _metadata(disc_id)
    unique_sources = []
    for name in image_sources:
        if name.lower() not in {value.lower() for value in unique_sources}:
            unique_sources.append(name)
    sector_count = sum(
        sizes[name.lower()] // _sector_size(
            next(
                track["mode"]
                for track in parsed_tracks
                if track["source"].lower() == name.lower()
            )
        )
        for name in unique_sources
    )
    warnings = (
        ("Cooked ISO input has no raw sectors or CD audio",)
        if any(track["mode"].endswith("/2048") for track in parsed_tracks)
        else ()
    )
    return DiscDescription(
        source=source,
        format=format_name,
        image_sources=tuple(image_sources),
        size=size,
        sha256=sha256,
        sha1=sha1,
        md5=md5,
        boot_path=boot_path,
        boot_sha256=boot_sha256,
        disc_id=disc_id,
        title=title,
        region=_region(disc_id),
        sector_count=sector_count,
        tracks=tracks,
        track_layout_sha256=_layout(tracks),
        protections=protections,
        complete=True,
        warnings=warnings,
    )


def _resolve_local(parent, name):
    relative = PurePosixPath(name.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise DiscAnalysisError("CUE image path leaves its directory")
    candidate = parent.joinpath(*relative.parts)
    if candidate.is_file():
        return candidate
    files = {
        str(path.relative_to(parent)).replace("\\", "/").lower(): path
        for path in parent.rglob("*")
        if path.is_file()
    }
    resolved = files.get(str(relative).lower())
    if resolved is None:
        raise DiscAnalysisError(f"missing CUE image {name}")
    return resolved


def _analyze_cue(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    parsed = _parse_cue_text(text)
    resolved = {}
    for track in parsed:
        key = track["source"].lower()
        resolved.setdefault(key, _resolve_local(path.parent, track["source"]))
    sizes = {key: image.stat().st_size for key, image in resolved.items()}
    streams = [resolved[key].open("rb") for key in resolved]
    try:
        description = _description(
            path,
            "cue",
            tuple(track["source"] for track in parsed),
            streams,
            parsed,
            sizes,
            resolved,
        )
        if "REM PSXFOUNDRY COOKED_ISO" in text:
            description = replace(
                description,
                warnings=("Cooked ISO input has no raw sectors or CD audio",),
            )
        return description
    finally:
        for stream in streams:
            stream.close()


def _analyze_raw(path, format_name=None):
    size = path.stat().st_size
    mode = detect_sector_mode(path)
    if mode is None:
        if size and size % 2352 == 0:
            mode = "MODE2/2352"
        elif path.suffix.lower() == ".iso" and size and size % 2048 == 0:
            mode = "MODE2/2048"
        else:
            raise DiscAnalysisError("disc image has no supported sector layout")
    parsed = [
        {
            "number": 1,
            "mode": mode,
            "source": path.name,
            "indexes": [(1, 0)],
        }
    ]
    with path.open("rb") as stream:
        return _description(
            path,
            format_name or path.suffix.lower().lstrip("."),
            (path.name,),
            [stream],
            parsed,
            {path.name.lower(): size},
            {path.name.lower(): path},
        )


def _analyze_ccd(path):
    parser = configparser.ConfigParser()
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            parser.read_file(handle)
    except (UnicodeDecodeError, configparser.Error) as error:
        raise DiscAnalysisError(f"invalid CCD file: {error}") from error

    image = _resolve_local(path.parent, path.with_suffix(".img").name)
    modes = {0: "AUDIO", 1: "MODE1/2352", 2: "MODE2/2352"}
    parsed = []
    for section in parser.sections():
        match = re.fullmatch(r"TRACK\s+(\d+)", section, re.IGNORECASE)
        if not match:
            continue
        mode_number = parser.getint(section, "MODE", fallback=-1)
        if mode_number not in modes:
            raise DiscAnalysisError(f"CCD {section} has an unsupported mode")
        indexes = []
        for key, value in parser.items(section):
            index_match = re.fullmatch(r"INDEX\s+(\d+)", key, re.IGNORECASE)
            if index_match:
                indexes.append((int(index_match.group(1)), int(value, 0)))
        if not indexes:
            raise DiscAnalysisError(f"CCD {section} has no index")
        parsed.append(
            {
                "number": int(match.group(1)),
                "mode": modes[mode_number],
                "source": image.name,
                "indexes": indexes,
            }
        )
    parsed.sort(key=lambda track: track["number"])
    if not parsed:
        raise DiscAnalysisError("CCD contains no tracks")
    if [track["number"] for track in parsed] != list(range(1, len(parsed) + 1)):
        raise DiscAnalysisError("CCD track numbers are not consecutive")
    with image.open("rb") as stream:
        return _description(
            path,
            "ccd",
            (image.name,),
            [stream],
            parsed,
            {image.name.lower(): image.stat().st_size},
            {image.name.lower(): image},
        )


def _incomplete_description(path, format_name, size, sha256, sha1, md5, warning):
    return DiscDescription(
        source=path,
        format=format_name,
        image_sources=(path.name,),
        size=size,
        sha256=sha256,
        sha1=sha1,
        md5=md5,
        boot_path=None,
        boot_sha256=None,
        disc_id=None,
        title=None,
        region=None,
        sector_count=None,
        tracks=(),
        track_layout_sha256=None,
        protections=(),
        complete=False,
        warnings=(warning,),
    )


def _analyze_chd(path):
    with path.open("rb") as stream:
        size, sha256, sha1, md5, _ = _hash_streams([stream])
    return _incomplete_description(
        path,
        "chd",
        size,
        sha256,
        sha1,
        md5,
        "CHD track metadata requires chdman analysis",
    )


def _safe_zip_members(archive):
    members = {}
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise DiscAnalysisError("ZIP contains an unsafe path")
        if info.flag_bits & 0x1:
            raise DiscAnalysisError("encrypted ZIP entries are not supported")
        if not info.is_dir():
            key = info.filename.lower()
            if key in members:
                raise DiscAnalysisError("ZIP contains duplicate case-insensitive paths")
            members[key] = info
    return members


def _analyze_zip(path):
    with zipfile.ZipFile(path) as archive:
        members = _safe_zip_members(archive)
        cue_members = [info for name, info in members.items() if name.endswith(".cue")]
        if len(cue_members) > 1:
            raise DiscAnalysisError("ZIP contains multiple CUE files")
        if cue_members:
            cue_info = cue_members[0]
            text = archive.read(cue_info).decode("utf-8-sig", errors="replace")
            parsed = _parse_cue_text(text)
            selected = {}
            for track in parsed:
                cue_parent = PurePosixPath(cue_info.filename).parent
                member_path = str(cue_parent / track["source"]).lower()
                if ".." in PurePosixPath(member_path).parts or member_path not in members:
                    raise DiscAnalysisError(f"missing ZIP image {track['source']}")
                selected.setdefault(track["source"].lower(), members[member_path])
            sizes = {key: info.file_size for key, info in selected.items()}
            streams = [archive.open(info) for info in selected.values()]
            try:
                return _description(
                    path,
                    "zip/cue",
                    tuple(track["source"] for track in parsed),
                    streams,
                    parsed,
                    sizes,
                )
            finally:
                for stream in streams:
                    stream.close()

        images = [
            info
            for name, info in members.items()
            if PurePosixPath(name).suffix.lower() in {".bin", ".img"}
        ]
        if len(images) != 1:
            raise DiscAnalysisError("ZIP must contain one disc image or one CUE set")
        info = images[0]
        if info.file_size == 0 or info.file_size % 2352:
            raise DiscAnalysisError("ZIP disc image size is not a multiple of 2352")
        parsed = [
            {
                "number": 1,
                "mode": "MODE2/2352",
                "source": info.filename,
                "indexes": [(1, 0)],
            }
        ]
        with archive.open(info) as stream:
            return _description(
                path,
                "zip/raw",
                (info.filename,),
                [stream],
                parsed,
                {info.filename.lower(): info.file_size},
            )


def analyze_disc(path):
    """Analyze one descriptor, image or archive without modifying it."""
    path = Path(path).resolve()
    if not path.is_file():
        raise DiscAnalysisError(f"disc input does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DiscAnalysisError(f"unsupported disc input: {suffix or path.name}")
    if suffix == ".cue":
        return _analyze_cue(path)
    if suffix in {".bin", ".img", ".iso"}:
        return _analyze_raw(path)
    if suffix == ".chd":
        return _analyze_chd(path)
    if suffix == ".zip":
        return _analyze_zip(path)
    return _analyze_ccd(path)


def _group_key(disc):
    value = disc.title or disc.source.stem
    value = re.sub(r"\[[^]]*]", " ", value)
    value = re.sub(r"\b(?:disc|disk|cd)\s*\d+\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())


def group_disc_sets(discs):
    """Group analyzed discs by detected title, then normalized filename."""
    groups = {}
    for disc in discs:
        groups.setdefault(_group_key(disc), []).append(disc)
    return tuple(
        DiscSet(
            next((disc.title for disc in values if disc.title), key or "Unknown game"),
            tuple(values),
        )
        for key, values in groups.items()
    )
