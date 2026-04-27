#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -z "${OPF_SSH_HOST:-}" ]; then
  echo "OPF_SSH_HOST is required" >&2
  exit 2
fi

if [ -z "${OPF_SSH_USER:-}" ]; then
  echo "OPF_SSH_USER is required" >&2
  exit 2
fi

OPF_SSH_PORT="${OPF_SSH_PORT:-22}"
OPF_BASE_URL="${OPF_BASE_URL:-http://localhost:8000}"
TARGET="$OPF_SSH_USER@$OPF_SSH_HOST"

shell_quote() {
  printf "'%s'" "$(printf "%s" "$1" | sed "s/'/'\\\\''/g")"
}

REMOTE_BASE_URL=$(shell_quote "$OPF_BASE_URL")

echo "== Remote extract API verification =="
echo "target=$TARGET"
echo "port=$OPF_SSH_PORT"
echo "base_url=$OPF_BASE_URL"
echo

ssh -p "$OPF_SSH_PORT" "$TARGET" "OPF_BASE_URL=$REMOTE_BASE_URL sh -s" < "$SCRIPT_DIR/verify_extract_api.sh"
