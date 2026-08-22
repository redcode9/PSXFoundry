"""Read and verify PlayStation EBOOT.PBP files."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import zlib


PBP_MAGIC = b"\x00PBP"
PSTITLE_MAGIC = b"PSTITLEIMG000000"
PSISO_MAGIC = b"PSISOIMG0000"
PSISO_BLOCK_SIZE = 0x9300
PSISO_DATA_OFFSET = 0x100000
PSISO_INDEX_OFFSET = 0x4000
PSISO_INDEX_SIZE = 32
MAX_DISCS = 5

SECTION_NAMES = (
    "param_sfo",
    "icon0",
    "icon1",
    "pic0",
    "pic1",
    "snd0",
    "data_psp",
    "data_psar",
)


class PbpFormatError(ValueError):
    """Raised when a PBP structure is incomplete or inconsistent."""


@dataclass(frozen=True)
class PbpSection:
    name: str
    offset: int
    size: int


@dataclass(frozen=True)
class PsisoBlock:
    data_offset: int
    stored_size: int
    sha1_prefix: bytes

    @property
    def has_checksum(self):
        return any(self.sha1_prefix)


@dataclass(frozen=True)
class AudioTrack:
    data_offset: int
    size: int


@dataclass(frozen=True)
class PsisoDisc:
    number: int
    offset: int
    disc_id: str
    title: str
    declared_size: int
    decoded_size: int
    decoded_sha256: str
    toc: bytes
    toc_lead_out: int
    config_area: bytes
    magic_word: int
    subchannel_records: int
    subchannel_sha256: str | None
    audio_tracks: tuple[AudioTrack, ...]
    blocks: tuple[PsisoBlock, ...]

    @property
    def sector_count(self):
        return self.decoded_size // 2352

    @property
    def verified_block_checksums(self):
        return sum(block.has_checksum for block in self.blocks)


@dataclass(frozen=True)
class PbpInspection:
    path: Path
    size: int
    version: int
    sections: tuple[PbpSection, ...]
    sfo: dict
    psar_wrapper: str
    discs: tuple[PsisoDisc, ...]


def _read_exact(handle, offset, size, description):
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise PbpFormatError(f"truncated {description}")
    return data


def _parse_sfo(data):
    if len(data) < 20 or data[:4] != b"\x00PSF":
        raise PbpFormatError("invalid PARAM.SFO")

    key_start, data_start, entry_count = struct.unpack_from("<III", data, 8)
    index_end = 20 + entry_count * 16
    if index_end > len(data) or key_start < index_end or data_start < key_start:
        raise PbpFormatError("invalid PARAM.SFO tables")

    values = {}
    for number in range(entry_count):
        entry_offset = 20 + number * 16
        key_offset, data_format, data_length, data_capacity, value_offset = (
            struct.unpack_from("<HHIII", data, entry_offset)
        )
        key_position = key_start + key_offset
        key_end = data.find(b"\x00", key_position, data_start)
        if key_position >= data_start or key_end < 0:
            raise PbpFormatError("invalid PARAM.SFO key")

        value_position = data_start + value_offset
        value_end = value_position + data_length
        capacity_end = value_position + data_capacity
        if value_end > len(data) or capacity_end > len(data):
            raise PbpFormatError("invalid PARAM.SFO value")

        try:
            key = data[key_position:key_end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise PbpFormatError("invalid PARAM.SFO key encoding") from error

        raw_value = data[value_position:value_end]
        if data_format == 0x0404:
            if len(raw_value) < 4:
                raise PbpFormatError(f"invalid PARAM.SFO integer {key}")
            value = struct.unpack_from("<I", raw_value)[0]
        elif data_format == 0x0204:
            try:
                value = raw_value.rstrip(b"\x00").decode("utf-8")
            except UnicodeDecodeError as error:
                raise PbpFormatError(f"invalid PARAM.SFO string {key}") from error
        else:
            value = raw_value
        values[key] = value
    return values


def _normalize_disc_id(raw):
    value = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    if len(value) == 11 and value[0] == "_" and value[5] == "_":
        return value[1:5] + value[6:]
    return value


def _disc_offsets(handle, psar_offset, psar_size):
    magic = _read_exact(handle, psar_offset, 16, "DATA.PSAR header")
    if magic == PSTITLE_MAGIC:
        wrapper = "PSTITLEIMG"
        offsets = []
        for number in range(MAX_DISCS):
            raw = _read_exact(
                handle,
                psar_offset + 0x200 + number * 4,
                4,
                "PSTITLEIMG disc table",
            )
            relative = struct.unpack("<I", raw)[0]
            if relative == 0:
                break
            if relative >= psar_size:
                raise PbpFormatError("PSTITLEIMG disc offset is outside DATA.PSAR")
            offsets.append(psar_offset + relative)
        if not offsets:
            raise PbpFormatError("PSTITLEIMG contains no discs")
        if offsets != sorted(set(offsets)):
            raise PbpFormatError("PSTITLEIMG disc offsets are not strictly ordered")
        return wrapper, offsets

    if magic[: len(PSISO_MAGIC)] == PSISO_MAGIC:
        return "PSISOIMG", [psar_offset]
    raise PbpFormatError("DATA.PSAR contains no supported PSISO image")


def _read_blocks(
    handle,
    disc_offset,
    declared_size,
    file_size,
    subchannel_offset,
):
    blocks = []
    maximum_entries = (PSISO_DATA_OFFSET - PSISO_INDEX_OFFSET) // PSISO_INDEX_SIZE
    expected_data_offset = 0
    for number in range(maximum_entries):
        relative_entry_offset = PSISO_INDEX_OFFSET + number * PSISO_INDEX_SIZE
        if subchannel_offset and relative_entry_offset == subchannel_offset:
            break
        entry = _read_exact(
            handle,
            disc_offset + relative_entry_offset,
            PSISO_INDEX_SIZE,
            "PSISO index",
        )
        data_offset, stored_size = struct.unpack_from("<IH", entry)
        if stored_size == 0:
            break
        if stored_size > PSISO_BLOCK_SIZE:
            raise PbpFormatError("PSISO block exceeds its decoded size")
        if data_offset != expected_data_offset:
            raise PbpFormatError("PSISO block offsets are not contiguous")
        data_end = PSISO_DATA_OFFSET + data_offset + stored_size
        if data_end > declared_size or disc_offset + data_end > file_size:
            raise PbpFormatError("PSISO block is outside its declared data")
        blocks.append(PsisoBlock(data_offset, stored_size, entry[8:24]))
        expected_data_offset += stored_size
    else:
        raise PbpFormatError("PSISO index has no terminator")

    if not blocks:
        raise PbpFormatError("PSISO contains no blocks")
    return tuple(blocks)


def _decode_block(handle, disc_offset, block):
    payload = _read_exact(
        handle,
        disc_offset + PSISO_DATA_OFFSET + block.data_offset,
        block.stored_size,
        "PSISO block",
    )
    if block.stored_size < PSISO_BLOCK_SIZE:
        try:
            payload = zlib.decompress(payload, wbits=-15)
        except zlib.error as error:
            raise PbpFormatError("invalid compressed PSISO block") from error
    if len(payload) != PSISO_BLOCK_SIZE:
        raise PbpFormatError("invalid decoded PSISO block size")
    if block.has_checksum and hashlib.sha1(payload).digest()[:16] != block.sha1_prefix:
        raise PbpFormatError("PSISO block checksum mismatch")
    return payload


def iter_decoded_blocks(path, disc):
    """Yield verified decoded blocks for one inspected disc."""
    with Path(path).open("rb") as handle:
        for block in disc.blocks:
            yield _decode_block(handle, disc.offset, block)


def _read_audio_tracks(handle, disc_offset, declared_size):
    tracks = []
    for number in range(98):
        entry = _read_exact(
            handle,
            disc_offset + 0x0C00 + number * 16,
            16,
            "PSISO audio table",
        )
        data_offset, size = struct.unpack_from("<II", entry)
        if data_offset == 0:
            break
        if PSISO_DATA_OFFSET + data_offset + size > declared_size:
            raise PbpFormatError("PSISO audio track is outside its declared data")
        tracks.append(AudioTrack(data_offset, size))
    return tuple(tracks)


def _bcd(value, description):
    high, low = value >> 4, value & 0x0F
    if high > 9 or low > 9:
        raise PbpFormatError(f"invalid BCD value in {description}")
    return high * 10 + low


def _toc_lead_out(toc):
    if tuple(toc[number * 10 + 2] for number in range(3)) != (0xA0, 0xA1, 0xA2):
        raise PbpFormatError("invalid PSISO TOC lead-in")
    minute = _bcd(toc[27], "PSISO TOC")
    second = _bcd(toc[28], "PSISO TOC")
    frame = _bcd(toc[29], "PSISO TOC")
    if second >= 60 or frame >= 75:
        raise PbpFormatError("invalid PSISO TOC position")
    lead_out = (minute * 60 + second) * 75 + frame
    if lead_out <= 0:
        raise PbpFormatError("invalid PSISO TOC disc length")
    return lead_out


def _inspect_disc(handle, file_size, number, offset):
    header = _read_exact(handle, offset, 0x1400, "PSISO header")
    if header[:12] != PSISO_MAGIC:
        raise PbpFormatError(f"disc {number + 1} has no PSISO header")

    declared_size = struct.unpack_from("<I", header, 12)[0]
    if declared_size < PSISO_DATA_OFFSET or offset + declared_size > file_size:
        raise PbpFormatError(f"disc {number + 1} has an invalid declared size")

    subchannel_offset, subchannel_records = struct.unpack_from("<II", header, 0x12D4)
    if subchannel_offset:
        if subchannel_offset < PSISO_INDEX_OFFSET:
            raise PbpFormatError("PSISO subchannel data overlaps its header")
        if (subchannel_offset - PSISO_INDEX_OFFSET) % PSISO_INDEX_SIZE:
            raise PbpFormatError("PSISO subchannel data is not index-aligned")

    blocks = _read_blocks(
        handle,
        offset,
        declared_size,
        file_size,
        subchannel_offset,
    )
    digest = hashlib.sha256()
    for block in blocks:
        digest.update(_decode_block(handle, offset, block))

    subchannel_sha256 = None
    if subchannel_offset or subchannel_records:
        if not subchannel_offset or not subchannel_records:
            raise PbpFormatError("incomplete PSISO subchannel pointer")
        subchannel_size = subchannel_records * 12
        if subchannel_offset + subchannel_size > PSISO_DATA_OFFSET:
            raise PbpFormatError("PSISO subchannel data overlaps disc payload")
        subchannels = _read_exact(
            handle,
            offset + subchannel_offset,
            subchannel_size,
            "PSISO subchannel data",
        )
        subchannel_sha256 = hashlib.sha256(subchannels).hexdigest()

    raw_title = header[0x122C:0x12B0].split(b"\x00", 1)[0]
    title = raw_title.decode("utf-8", errors="replace")
    toc = header[0x800:0xBFC]
    return PsisoDisc(
        number=number + 1,
        offset=offset,
        disc_id=_normalize_disc_id(header[0x400:0x40B]),
        title=title,
        declared_size=declared_size,
        decoded_size=len(blocks) * PSISO_BLOCK_SIZE,
        decoded_sha256=digest.hexdigest(),
        toc=toc,
        toc_lead_out=_toc_lead_out(toc),
        config_area=header[0x420:0x800],
        magic_word=struct.unpack_from("<I", header, 0x12B0)[0],
        subchannel_records=subchannel_records,
        subchannel_sha256=subchannel_sha256,
        audio_tracks=_read_audio_tracks(handle, offset, declared_size),
        blocks=blocks,
    )


def inspect_pbp(path):
    """Parse a PBP and verify every decoded PSISO block."""
    path = Path(path)
    file_size = path.stat().st_size
    if file_size < 0x28:
        raise PbpFormatError("truncated PBP header")

    with path.open("rb") as handle:
        header = _read_exact(handle, 0, 0x28, "PBP header")
        if header[:4] != PBP_MAGIC:
            raise PbpFormatError("invalid PBP magic")
        version = struct.unpack_from("<I", header, 4)[0]
        offsets = struct.unpack_from("<8I", header, 8)
        if offsets[0] < 0x28 or list(offsets) != sorted(offsets):
            raise PbpFormatError("PBP section offsets are not ordered")
        if offsets[-1] > file_size:
            raise PbpFormatError("PBP section offset is outside the file")

        section_ends = offsets[1:] + (file_size,)
        sections = tuple(
            PbpSection(name, offset, end - offset)
            for name, offset, end in zip(SECTION_NAMES, offsets, section_ends)
        )
        sfo_data = _read_exact(
            handle,
            sections[0].offset,
            sections[0].size,
            "PARAM.SFO",
        )
        sfo = _parse_sfo(sfo_data)
        wrapper, offsets = _disc_offsets(
            handle,
            sections[-1].offset,
            sections[-1].size,
        )
        discs = tuple(
            _inspect_disc(handle, file_size, number, offset)
            for number, offset in enumerate(offsets)
        )

    return PbpInspection(
        path=path,
        size=file_size,
        version=version,
        sections=sections,
        sfo=sfo,
        psar_wrapper=wrapper,
        discs=discs,
    )
