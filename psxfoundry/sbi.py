"""Read and resolve LibCrypt SBI files."""

from dataclasses import dataclass
from html.parser import HTMLParser
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import tempfile
import time
from urllib.parse import unquote, urljoin, urlparse


SBI_INDEX_URL = "https://psxdatacenter.com/sbifiles.html"
SBI_HEADER = b"SBI\x00"
MAX_INDEX_SIZE = 512 * 1024
MAX_ARCHIVE_SIZE = 1024 * 1024
MAX_SBI_SIZE = 128 * 1024
INDEX_MAX_AGE = 7 * 24 * 60 * 60
SERIAL_PATTERN = re.compile(r"(?:SCES|SLES)[-_ .]?(\d{3})[-_ .]?(\d{2})", re.I)
LIBCRYPT_SECTOR_PAIRS = (
    (15, 14105, 14110),
    (14, 14231, 14236),
    (13, 14485, 14490),
    (12, 14579, 14584),
    (11, 14649, 14654),
    (10, 14899, 14904),
    (9, 15056, 15061),
    (8, 15130, 15135),
    (7, 15242, 15247),
    (6, 15312, 15317),
    (5, 15378, 15383),
    (4, 15628, 15633),
    (3, 15919, 15924),
    (2, 16031, 16036),
    (1, 16101, 16106),
    (0, 16167, 16172),
)
PBP_START_RECORD = bytes.fromhex("ffffffff00000000ffffffff")
PBP_END_RECORD = b"\xff" * 12


class SbiError(ValueError):
    pass


class SbiDownloadError(SbiError):
    pass


@dataclass(frozen=True)
class SbiEntry:
    sector: int
    q_data: bytes


@dataclass(frozen=True)
class SbiData:
    entries: tuple[SbiEntry, ...]
    magic_word: int
    sha256: str

    def to_pbp_subchannels(self):
        records = [PBP_START_RECORD]
        for entry in self.entries:
            q_data = entry.q_data
            records.append(
                struct.pack("<I", entry.sector - 150)
                + q_data[1:6]
                + q_data[7:10]
            )
        records.append(PBP_END_RECORD)
        return b"".join(records)


@dataclass(frozen=True)
class SbiSelection:
    path: Path
    origin: str
    data: SbiData


@dataclass(frozen=True)
class SbiResolution:
    selection: SbiSelection | None
    error: str | None


def _from_bcd(value):
    high, low = value >> 4, value & 0x0F
    if high > 9 or low > 9:
        raise SbiError(f"invalid packed BCD value 0x{value:02x}")
    return high * 10 + low


def _magic_word(sectors):
    value = 0
    for bit, first, second in LIBCRYPT_SECTOR_PAIRS:
        present = (first in sectors, second in sectors)
        if present[0] != present[1]:
            raise SbiError(
                f"incomplete LibCrypt sector pair {first}/{second}"
            )
        if present[0]:
            value |= 1 << bit
    return value


def parse_sbi(data, *, expected_magic_word=None, sector_count=None):
    if not isinstance(data, bytes):
        data = bytes(data)
    if len(data) > MAX_SBI_SIZE:
        raise SbiError("SBI file is too large")
    if not data.startswith(SBI_HEADER):
        raise SbiError("SBI header is invalid")
    if (len(data) - len(SBI_HEADER)) % 14:
        raise SbiError("SBI record table is truncated")

    entries = []
    sectors = set()
    for offset in range(4, len(data), 14):
        minute, second, frame, record_type = data[offset : offset + 4]
        minute = _from_bcd(minute)
        second = _from_bcd(second)
        frame = _from_bcd(frame)
        if second >= 60 or frame >= 75:
            raise SbiError("SBI record position is invalid")
        if record_type != 1:
            raise SbiError(f"unsupported SBI record type {record_type}")
        sector = (minute * 60 + second) * 75 + frame
        if sector < 150:
            raise SbiError("SBI record precedes the first data sector")
        if sector_count is not None and sector >= sector_count + 150:
            raise SbiError(f"SBI record {sector} is outside the disc")
        if sector in sectors:
            raise SbiError(f"duplicate SBI record for sector {sector}")
        sectors.add(sector)
        entries.append(SbiEntry(sector, data[offset + 4 : offset + 14]))

    if not entries:
        raise SbiError("SBI file contains no records")
    magic_word = _magic_word(sectors)
    if expected_magic_word is not None and magic_word != expected_magic_word:
        raise SbiError(
            "SBI magic word does not match the loaded disc "
            f"(0x{magic_word:04x}, expected 0x{expected_magic_word:04x})"
        )
    return SbiData(
        tuple(entries),
        magic_word,
        hashlib.sha256(data).hexdigest(),
    )


def load_sbi(path, *, expected_magic_word=None, sector_count=None):
    path = Path(path).expanduser().resolve()
    try:
        data = path.read_bytes()
    except OSError as error:
        raise SbiError(f"could not read SBI file: {path}") from error
    return parse_sbi(
        data,
        expected_magic_word=expected_magic_word,
        sector_count=sector_count,
    )


def _normalized_serial(value):
    match = SERIAL_PATTERN.search(value)
    if not match:
        return None
    prefix = match.group(0)[:4].upper()
    return prefix + "".join(match.groups())


def find_local_sbi(disc_path, disc_id=None):
    disc_path = Path(disc_path).expanduser()
    try:
        candidates = sorted(
            (
                path
                for path in disc_path.parent.iterdir()
                if path.is_file() and path.suffix.casefold() == ".sbi"
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        return None

    exact_name = disc_path.with_suffix(".sbi").name.casefold()
    exact = [path for path in candidates if path.name.casefold() == exact_name]
    if exact:
        return exact[0].resolve()

    if disc_id:
        serial = _normalized_serial(disc_id)
        matches = [
            path
            for path in candidates
            if _normalized_serial(path.stem) == serial
        ]
        if len(matches) == 1:
            return matches[0].resolve()
    return None


class _IndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def parse_sbi_index(data, base_url=SBI_INDEX_URL):
    try:
        text = data.decode("windows-1252")
    except UnicodeDecodeError as error:
        raise SbiDownloadError("SBI index encoding is invalid") from error
    parser = _IndexParser()
    parser.feed(text)
    index = {}
    for href in parser.links:
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "psxdatacenter.com",
            "www.psxdatacenter.com",
        }:
            continue
        if not parsed.path.casefold().startswith("/sbifiles/"):
            continue
        if not parsed.path.casefold().endswith(".7z"):
            continue
        serial = _normalized_serial(unquote(parsed.path))
        if serial:
            index.setdefault(serial, []).append(url)
    return {serial: tuple(urls) for serial, urls in index.items()}


def _download(url, maximum_size):
    try:
        import requests
    except ImportError as error:
        raise SbiDownloadError("online SBI lookup requires requests") from error

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(5, 20),
        ) as response:
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > maximum_size:
                raise SbiDownloadError("online SBI response is too large")
            chunks = []
            size = 0
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > maximum_size:
                    raise SbiDownloadError("online SBI response is too large")
                chunks.append(chunk)
    except SbiDownloadError:
        raise
    except Exception as error:
        raise SbiDownloadError(f"could not download {url}") from error
    return b"".join(chunks)


def _write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _cached_index(cache_dir, fetch):
    cache_path = Path(cache_dir) / "index.html"
    fresh = (
        cache_path.is_file()
        and time.time() - cache_path.stat().st_mtime <= INDEX_MAX_AGE
    )
    if fresh:
        return cache_path.read_bytes()
    try:
        data = fetch(SBI_INDEX_URL, MAX_INDEX_SIZE)
        _write_atomic(cache_path, data)
        return data
    except Exception:
        if cache_path.is_file():
            return cache_path.read_bytes()
        raise


def _archive_member(archive_path):
    extractor = shutil.which("bsdtar")
    if extractor is None and Path("/usr/bin/bsdtar").is_file():
        extractor = "/usr/bin/bsdtar"
    if extractor is None:
        raise SbiDownloadError("bsdtar is required to unpack online SBI files")
    try:
        result = subprocess.run(
            [extractor, "-tf", str(archive_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SbiDownloadError("could not inspect SBI archive") from error
    members = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().casefold().endswith(".sbi")
    ]
    safe_members = []
    for member in members:
        archive_path = PurePosixPath(member.replace("\\", "/"))
        if not archive_path.is_absolute() and ".." not in archive_path.parts:
            safe_members.append(member)
    if len(safe_members) != 1:
        raise SbiDownloadError("SBI archive must contain one SBI file")
    return extractor, safe_members[0]


def _extract_sbi(archive_path):
    extractor, member = _archive_member(archive_path)
    try:
        process = subprocess.Popen(
            [extractor, "-xOf", str(archive_path), member],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        data = process.stdout.read(MAX_SBI_SIZE + 1)
        if len(data) > MAX_SBI_SIZE:
            process.kill()
            process.communicate()
            raise SbiDownloadError("SBI archive expands beyond the size limit")
        try:
            _, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise SbiDownloadError("SBI archive extraction timed out")
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise SbiDownloadError(detail or "could not unpack SBI archive")
        return data
    except SbiDownloadError:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise SbiDownloadError("could not unpack SBI archive") from error


def _cached_selection(cache_dir, disc_id, expected_magic_word, sector_count):
    selections = []
    for path in sorted(Path(cache_dir).glob(f"{disc_id}-*.sbi")):
        try:
            data = load_sbi(
                path,
                expected_magic_word=expected_magic_word,
                sector_count=sector_count,
            )
        except SbiError:
            continue
        selections.append(SbiSelection(path.resolve(), "cached", data))
    unique = {selection.data.sha256: selection for selection in selections}
    return next(iter(unique.values())) if len(unique) == 1 else None


def resolve_online_sbi(
    disc_id,
    *,
    expected_magic_word,
    sector_count=None,
    cache_dir,
    fetch=_download,
):
    disc_id = _normalized_serial(disc_id)
    if disc_id is None:
        raise SbiDownloadError("disc serial is not valid for SBI lookup")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cached = _cached_selection(
        cache_dir,
        disc_id,
        expected_magic_word,
        sector_count,
    )
    if cached is not None:
        return cached

    index = parse_sbi_index(_cached_index(cache_dir, fetch))
    candidates = index.get(disc_id, ())
    if not candidates:
        raise SbiDownloadError(f"PSX DataCenter has no SBI for {disc_id}")

    matches = {}
    errors = []
    for url in candidates:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        archive_path = cache_dir / f"{disc_id}-{key}.7z"
        try:
            if not archive_path.is_file():
                _write_atomic(archive_path, fetch(url, MAX_ARCHIVE_SIZE))
            payload = _extract_sbi(archive_path)
            data = parse_sbi(
                payload,
                expected_magic_word=expected_magic_word,
                sector_count=sector_count,
            )
            matches.setdefault(data.sha256, (payload, data, key))
        except SbiError as error:
            errors.append(str(error))

    if len(matches) != 1:
        if not matches:
            detail = "; ".join(dict.fromkeys(errors))
            raise SbiDownloadError(detail or f"no valid SBI found for {disc_id}")
        raise SbiDownloadError(f"multiple SBI revisions match {disc_id}")

    payload, data, key = next(iter(matches.values()))
    path = cache_dir / f"{disc_id}-{key}.sbi"
    _write_atomic(path, payload)
    return SbiSelection(path.resolve(), "downloaded", data)


def resolve_sbi(
    disc_path,
    disc_id,
    *,
    expected_magic_word=None,
    sector_count=None,
    cache_dir=None,
    online=True,
):
    local_path = find_local_sbi(disc_path, disc_id)
    local_error = None
    if local_path is not None:
        try:
            data = load_sbi(
                local_path,
                expected_magic_word=expected_magic_word,
                sector_count=sector_count,
            )
            return SbiResolution(
                SbiSelection(local_path, "local", data),
                None,
            )
        except SbiError as error:
            local_error = str(error)

    if not expected_magic_word or not online:
        return SbiResolution(None, local_error)
    if cache_dir is None:
        raise ValueError("cache_dir is required for online SBI lookup")
    try:
        selection = resolve_online_sbi(
            disc_id,
            expected_magic_word=expected_magic_word,
            sector_count=sector_count,
            cache_dir=cache_dir,
        )
        return SbiResolution(selection, None)
    except SbiError as error:
        details = [item for item in (local_error, str(error)) if item]
        return SbiResolution(None, "; ".join(details))
