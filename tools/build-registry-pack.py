#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from psxfoundry.updates import build_registry_pack


def main():
    parser = argparse.ArgumentParser(description="Build a signed registry pack")
    parser.add_argument("--version", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()
    private_key = args.private_key.read_bytes()
    pack = build_registry_pack(
        args.output,
        args.version,
        args.repository,
        private_key,
    )
    print(f"Registry {pack.version}: {len(pack.files)} files")


if __name__ == "__main__":
    main()
