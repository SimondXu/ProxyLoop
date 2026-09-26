#!/usr/bin/env bash
# Clone the pinned third-party repositories into $EXTERNAL_DIR (default: external/, git-ignored).
# Pins and licences: third_party/README.md.
#
# Data preservation: this script never modifies an existing directory and never deletes anything.
# - $EXTERNAL_DIR/<name> absent: init, fetch and check out the pin, then verify it.
# - $EXTERNAL_DIR/<name> present: read-only verification. If it is not a git repository, HEAD is not
#   the pin, or the checkout is dirty, print an error naming it and exit 1 without writing to it.
# external/pine-ai-tasks/ is the user's own mirror: it is user data and this script never touches it.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dest="${EXTERNAL_DIR:-$root/external}"

pins=(
  "TalkAct https://github.com/19PINE-AI/TalkAct.git 7d70007f72d45ddfc1a14e8e229b6d444e4919a2"
  "principal-loyalty https://github.com/19PINE-AI/principal-loyalty.git 776e92137acc784f3088ab94587c6c13afed488c"
)

fail() {
  echo "error: $1" >&2
  exit 1
}

mkdir -p "$dest"
for pin in "${pins[@]}"; do
  read -r name url sha <<<"$pin"
  dir="$dest/$name"
  if [ ! -e "$dir" ] && [ ! -L "$dir" ]; then
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch -q --depth 1 origin "$sha"
    git -C "$dir" checkout -q --detach "$sha"
  fi
  # From here on, read-only: no command below writes to $dir.
  [ -d "$dir" ] && [ ! -L "$dir" ] || fail "$dir exists and is not a directory; left untouched"
  top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$top" ] && [ "$(cd "$top" && pwd -P)" = "$(cd "$dir" && pwd -P)" ] ||
    fail "$dir exists and is not a git repository; left untouched"
  head="$(git -C "$dir" rev-parse -q --verify HEAD || true)"
  [ "$head" = "$sha" ] || fail "$dir is at '${head:-no commit}', pinned $sha; left untouched"
  [ -z "$(git --no-optional-locks -C "$dir" status --porcelain)" ] ||
    fail "$dir has local changes, so it does not reproduce pin $sha; left untouched"
  echo "$name $head verified"
done
