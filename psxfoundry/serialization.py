"""Stable serialization used by caches and signed manifests."""

import json


def canonical_json_bytes(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
