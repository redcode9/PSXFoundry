"""PSP conversion decisions."""


def track_end_offset(track, sector_length=2352):
    """Return the byte offset immediately after a track's final sector."""
    indexes = track.get("INDEX", {})
    if not indexes:
        raise ValueError("track has no indexes")

    final_index = indexes[max(indexes)]
    stop_sector = int(final_index["STOPSECT"])
    if stop_sector < 0:
        raise ValueError("track stop sector must not be negative")
    return (stop_sector + 1) * sector_length


def whole_disc_modes(disc_count, aea_files, use_cdda=False):
    """Return whether each PSISO should retain its complete source image."""
    if disc_count < 0:
        raise ValueError("disc_count must not be negative")
    if use_cdda:
        return [True] * disc_count

    modes = []
    for index in range(disc_count):
        atrac_tracks = aea_files[index] if index < len(aea_files) else []
        modes.append(not bool(atrac_tracks))
    return modes
