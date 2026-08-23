#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
SOURCE="$SCRIPT_DIR/psxfoundry"
DEFAULT_DESTINATION="$HOME/.local/bin"

[[ -x "$SOURCE" ]] || {
    printf 'The psxfoundry executable is missing beside this installer.\n' >&2
    exit 1
}

if [[ -n "${PSXFOUNDRY_INSTALL_DEST:-${POPFE_INSTALL_DEST:-}}" ]]; then
    DESTINATION="${PSXFOUNDRY_INSTALL_DEST:-$POPFE_INSTALL_DEST}"
else
    printf 'Install the PSXFoundry command-line tool.\n'
    printf 'Destination directory [%s]: ' "$DEFAULT_DESTINATION"
    IFS= read -r DESTINATION
    DESTINATION="${DESTINATION:-$DEFAULT_DESTINATION}"
fi

case "$DESTINATION" in
    '~') DESTINATION="$HOME" ;;
    '~/'*) DESTINATION="$HOME/${DESTINATION#\~/}" ;;
esac

mkdir -p "$DESTINATION"
TEMPORARY="$(mktemp "$DESTINATION/.psxfoundry.XXXXXX")"
cleanup() {
    [[ ! -e "$TEMPORARY" ]] || rm -f "$TEMPORARY"
}
trap cleanup EXIT
cp "$SOURCE" "$TEMPORARY"
chmod 755 "$TEMPORARY"
mv -f "$TEMPORARY" "$DESTINATION/psxfoundry"
if [[ ! -e "$DESTINATION/pop-fe" && ! -L "$DESTINATION/pop-fe" ]]; then
    ln -s psxfoundry "$DESTINATION/pop-fe"
fi

printf '\nInstalled: %s/psxfoundry\n' "$DESTINATION"
printf 'If that directory is not on PATH, run it with the full path shown above.\n'
