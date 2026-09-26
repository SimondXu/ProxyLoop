#!/usr/bin/env bash
# Clone the pinned third-party repositories into $EXTERNAL_DIR (default: external/, git-ignored).
# Idempotent: a clone already at its pin is only re-verified. Fails if a checkout is not exactly
# its pinned sha or has local changes. Pins and licences: third_party/README.md.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dest="${EXTERNAL_DIR:-$root/external}"

pins=(
  "TalkAct https://github.com/19PINE-AI/TalkAct.git 7d70007f72d45ddfc1a14e8e229b6d444e4919a2"
  "principal-loyalty https://github.com/19PINE-AI/principal-loyalty.git 776e92137acc784f3088ab94587c6c13afed488c"
)

mkdir -p "$dest"
for pin in "${pins[@]}"; do
  read -r name url sha <<<"$pin"
  dir="$dest/$name"
  if [ ! -d "$dir/.git" ]; then
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
  fi
  if [ "$(git -C "$dir" rev-parse -q --verify HEAD || true)" != "$sha" ]; then
    git -C "$dir" fetch -q --depth 1 origin "$sha"
    git -C "$dir" checkout -q --detach "$sha"
  fi
  head="$(git -C "$dir" rev-parse HEAD)"
  if [ "$head" != "$sha" ]; then
    echo "error: $name is at $head, pinned $sha" >&2
    exit 1
  fi
  if [ -n "$(git -C "$dir" status --porcelain)" ]; then
    echo "error: $dir has local changes; it does not reproduce pin $sha" >&2
    exit 1
  fi
  echo "$name $head verified"
done
