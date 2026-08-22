#!/usr/bin/env python3

import argparse
import os
from pathlib import Path

from Crypto.PublicKey import ECC


def main():
    parser = argparse.ArgumentParser(description="Create an Ed25519 registry key")
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    args = parser.parse_args()
    if args.private_key.exists() or args.public_key.exists():
        raise SystemExit("Refusing to replace an existing registry key")

    key = ECC.generate(curve="Ed25519")
    args.private_key.parent.mkdir(parents=True, exist_ok=True)
    args.public_key.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        args.private_key,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(key.export_key(format="PEM"))
        handle.write("\n")
    args.public_key.write_text(
        key.public_key().export_key(format="PEM") + "\n",
        encoding="ascii",
    )
    print(args.public_key)


if __name__ == "__main__":
    main()
