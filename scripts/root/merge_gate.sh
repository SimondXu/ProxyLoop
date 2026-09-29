#!/usr/bin/env bash
# The main root's merge gate (S1-ROOT-25): the manual merge ritual as one script.
#
#   merge_gate.sh check  <PR>
#   merge_gate.sh merge  <PR> [--allow-disjoint] [--dry-run]
#   merge_gate.sh update <PR> [--dry-run]
#   merge_gate.sh batch  <PR>... [--dry-run]
#
# Run it from the shared checkout (or any worktree of it). It uses gh and git only.
# - "checks" are branch protection's required contexts on the PR's exact head sha; a
#   missing context is PENDING.
# - main=CONTAINED: the head contains origin/main. DISJOINT: it does not, but the paths
#   changed on main since the merge-base and the PR's paths do not intersect. Otherwise
#   OVERLAP:<paths>.
# - check also reports main_ci=success|failure|pending|unknown: the ci.yml push run for
#   origin/main's current tip sha (the full `make check`); no run for that sha yet is
#   pending, a gh error unknown. Informational, it never blocks. A red one prints a
#   WARNING line above the check line. (It is keyed on the sha, not "the latest run",
#   because `gh run list --branch main --limit 1` can transiently return an old run.)
# - merge squash-merges with --match-head-commit and confirms state MERGED afterwards.
# - batch merges every head into a detached scratch worktree at origin/main, runs
#   `HF_HUB_OFFLINE=1 make check` (and `make web-test` when apps/web/** is touched) there,
#   then merges each unchanged head and verifies origin/main's tree is the tested tree.
#   MAKE=<cmd> overrides make.
# - --dry-run prints the mutating commands instead of running them (fetches still run).
# Never --admin, never --auto, never deletes a branch, never pulls the shared checkout.
# The last line of every mode is one line for the root log. Exit 1: refused or failed;
# exit 2: usage.
set -euo pipefail

# Branch protection's required contexts, as a jq array (edit here if protection changes).
REQUIRED_JQ='["check","task-id","web","shellcheck"]'
MAKE_CMD="${MAKE:-make}"

# One line "<head> <state> <base ref>", then "<context> ok|pending|failed" per required
# context. A context with several runs is failed if any failed, else pending if any pends.
# shellcheck disable=SC2016  # $n, $r, $vs are jq variables, not shell expansions
ROLLUP_JQ='
def verdict:
  if .__typename == "StatusContext" then
    (if .state == "SUCCESS" then "ok"
     elif (.state == "PENDING" or .state == "EXPECTED") then "pending"
     else "failed" end)
  else
    (if .status != "COMPLETED" then "pending"
     elif .conclusion == "SUCCESS" then "ok"
     else "failed" end)
  end;
(.statusCheckRollup // []) as $rollup
| ($rollup | map({n: (.name // .context), v: verdict})) as $r
| "\(.headRefOid) \(.state) \(.baseRefName)",
  ('"$REQUIRED_JQ"'[] as $n
   | [$r[] | select(.n == $n) | .v] as $vs
   | if ($vs | length) == 0 then "\($n) pending"
     elif ($vs | any(. == "failed")) then "\($n) failed"
     elif ($vs | any(. == "pending")) then "\($n) pending"
     else "\($n) ok" end)'

usage() {
  sed -n '4,7p' "$0" | sed 's/^# *//' >&2
  exit 2
}

die() {
  echo "merge_gate: $1" >&2
  exit 1
}

short() { printf '%s' "${1:0:7}"; }

# Sorted, de-duplicated, non-empty lines of $1 (C collation, as comm needs).
lines() { printf '%s\n' "$1" | sed '/^$/d' | LC_ALL=C sort -u; }

# Paths in both newline lists $1 and $2, comma-joined.
common_paths() { LC_ALL=C comm -12 <(lines "$1") <(lines "$2") | paste -sd, -; }

repo_root() { dirname "$(git rev-parse --path-format=absolute --git-common-dir)"; }

reminder() {
  echo "reminder: the shared checkout was not pulled; pull it when safe: git -C $(repo_root) pull --ff-only"
}

# inspect_pr <n>: sets PR_HEAD PR_STATE PR_BASE_REF CHECKS BASE_SHA PR_FILES MAIN_REL READY.
inspect_pr() {
  local n="$1" out a b c first=1 failed="" pending=0 mb both
  PR_HEAD=""
  out="$(gh pr view "$n" --json headRefOid,state,baseRefName,statusCheckRollup --jq "$ROLLUP_JQ")" ||
    die "gh pr view $n failed"
  while read -r a b c; do
    if ((first)); then
      PR_HEAD="$a" PR_STATE="$b" PR_BASE_REF="$c" first=0
      continue
    fi
    case "$b" in
      failed) failed="$failed,$a" ;;
      pending) pending=1 ;;
    esac
  done <<<"$out"
  [ -n "${PR_HEAD:-}" ] || die "gh pr view $n returned no head"
  if [ -n "$failed" ]; then
    CHECKS="FAILED:${failed#,}"
  elif ((pending)); then
    CHECKS=PENDING
  else
    CHECKS=GREEN
  fi

  git fetch -q origin main "pull/$n/head" || die "git fetch of main and PR $n failed"
  git cat-file -e "$PR_HEAD^{commit}" 2>/dev/null ||
    die "PR $n head $PR_HEAD is not fetched (did the PR move?)"
  BASE_SHA="$(git rev-parse origin/main)"
  mb="$(git merge-base origin/main "$PR_HEAD")"
  PR_FILES="$(git diff --name-only --no-renames "$mb" "$PR_HEAD")"
  if git merge-base --is-ancestor origin/main "$PR_HEAD"; then
    MAIN_REL=CONTAINED
  else
    both="$(common_paths "$PR_FILES" "$(git diff --name-only --no-renames "$mb" origin/main)")"
    if [ -z "$both" ]; then MAIN_REL=DISJOINT; else MAIN_REL="OVERLAP:$both"; fi
  fi
  READY=no
  if [ "$CHECKS" = GREEN ] && [ "$MAIN_REL" = CONTAINED ] &&
    [ "$PR_STATE" = OPEN ] && [ "$PR_BASE_REF" = main ]; then
    READY=yes
  fi
  if [ "$PR_STATE" != OPEN ] || [ "$PR_BASE_REF" != main ]; then
    echo "note: PR $n is $PR_STATE with base $PR_BASE_REF (the gate needs OPEN on main)" >&2
  fi
}

check_line() {
  echo "PR $1 head=$(short "$PR_HEAD") base=$(short "$BASE_SHA") checks=$CHECKS main=$MAIN_REL ready=$READY"
}

# merge_and_confirm <n> <head>: squash-merge on the exact head, then confirm MERGED.
# Sets MERGE_SHA, or FAIL_REASON and returns 1.
merge_and_confirm() {
  local st oid
  if ! gh pr merge "$1" --squash --match-head-commit "$2"; then
    FAIL_REASON="gh pr merge $1 --match-head-commit $(short "$2") failed"
    return 1
  fi
  read -r st oid <<<"$(gh pr view "$1" --json state,mergeCommit \
    --jq '.state + " " + (.mergeCommit.oid // "")' || true)"
  if [ "${st:-}" != MERGED ] || [ -z "${oid:-}" ]; then
    FAIL_REASON="PR $1 is ${st:-unknown} after gh pr merge, not MERGED"
    return 1
  fi
  MERGE_SHA="$oid"
}

# main_ci: sets MAIN_CI (success|failure|pending|unknown) and MAIN_CI_URL from the ci.yml
# push run of origin/main's current tip sha. Informational, never an error: no run for
# the tip yet is pending; a git or gh failure is unknown.
# shellcheck disable=SC2016  # jq program, no shell expansions
MAIN_CI_JQ='
if length == 0 then "pending"
else .[0]
  | (if .status != "completed" then "pending"
     elif .conclusion == "success" then "success"
     elif (.conclusion | IN("failure", "timed_out", "startup_failure")) then "failure"
     else "unknown" end) + " " + (.url // "")
end'

main_ci() {
  local out tip
  MAIN_CI=unknown MAIN_CI_URL=""
  tip="$(git rev-parse --verify -q origin/main)" || return 0
  out="$(gh run list --workflow ci.yml --event push --commit "$tip" --limit 1 \
    --json status,conclusion,url --jq "$MAIN_CI_JQ" 2>/dev/null)" || return 0
  read -r MAIN_CI MAIN_CI_URL <<<"$out"
  MAIN_CI="${MAIN_CI:-unknown}"
}

# check adds main_ci=<...>, the full-check result for main's current tip (it never gates a
# merge), and a WARNING line before the check line when that run is red.
cmd_check() {
  inspect_pr "$1"
  main_ci
  if [ "$MAIN_CI" = failure ]; then
    echo "WARNING: main's full check is red (${MAIN_CI_URL:-no url})"
  fi
  echo "$(check_line "$1") main_ci=$MAIN_CI"
}

cmd_merge() {
  local n="$1" reason=""
  inspect_pr "$n"
  check_line "$n"
  [ "$PR_STATE" = OPEN ] || reason="state is $PR_STATE"
  [ "$PR_BASE_REF" = main ] || reason="base is $PR_BASE_REF, not main"
  [ "$CHECKS" = GREEN ] || reason="checks=$CHECKS"
  case "$MAIN_REL" in
    CONTAINED) ;;
    DISJOINT)
      ((ALLOW_DISJOINT)) ||
        reason="head does not contain main (DISJOINT): pass --allow-disjoint or run: $0 update $n"
      ;;
    *) reason="main=$MAIN_REL: run $0 update $n" ;;
  esac
  if [ -n "$reason" ]; then
    echo "MERGE REFUSED $n: $reason"
    exit 1
  fi
  if ((DRY_RUN)); then
    echo "would run: gh pr merge $n --squash --match-head-commit $PR_HEAD"
    echo "would run: gh pr view $n --json state,mergeCommit (expect MERGED)"
    echo "DRY-RUN merge $n head=$(short "$PR_HEAD") main=$MAIN_REL: nothing changed"
    return
  fi
  if ! merge_and_confirm "$n" "$PR_HEAD"; then
    echo "MERGE FAILED $n: $FAIL_REASON"
    exit 1
  fi
  reminder
  echo "MERGED $n -> $(short "$MERGE_SHA")"
}

cmd_update() {
  local n="$1" old new i
  old="$(gh pr view "$n" --json headRefOid --jq .headRefOid)" || die "gh pr view $n failed"
  if ((DRY_RUN)); then
    echo "would run: gh pr update-branch $n"
    echo "DRY-RUN update $n head=$(short "$old"): nothing changed"
    return
  fi
  if ! gh pr update-branch "$n"; then
    echo "UPDATE FAILED $n: gh pr update-branch failed (head=$(short "$old"))"
    exit 1
  fi
  # GitHub moves the head asynchronously: poll for up to ~30 s.
  new="$old"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    new="$(gh pr view "$n" --json headRefOid --jq .headRefOid)" || die "gh pr view $n failed"
    [ "$new" = "$old" ] || break
    [ "$i" = 10 ] || sleep 3
  done
  if [ "$new" = "$old" ]; then
    echo "UPDATED $n head=$new (unchanged: already up to date, or GitHub is still updating)"
  else
    echo "UPDATED $n head=$new (was $(short "$old")); wait for CI on the new head"
  fi
}

# batch_fail <reason>: stop, keep the worktree, say what was and wasn't merged.
batch_fail() {
  local rest="" p
  for p in "${PRS[@]}"; do
    case ",$MERGED_PRS," in *",$p,"*) ;; *) rest="$rest,$p" ;; esac
  done
  echo "BATCH FAILED: $1; merged=${MERGED_LIST:-none}; not merged=${rest#,}; worktree=$WT_STATE"
  exit 1
}

run_make() { # run_make <target> <log>; prints "make <target>: PASS|FAIL (log: <log>)"
  if (cd "$WT" && HF_HUB_OFFLINE=1 "$MAKE_CMD" "$1") >"$2" 2>&1; then
    echo "make $1: PASS (log: $2)"
  else
    echo "make $1: FAIL (log: $2)"
    return 1
  fi
}

cmd_batch() {
  local n i seen="" both web=0 base tree expected cur final
  PRS=("$@") HEADS=() MERGED_PRS="" MERGED_LIST="" WT_STATE="not created"
  for n in "${PRS[@]}"; do
    inspect_pr "$n"
    check_line "$n"
    [ "$PR_STATE" = OPEN ] && [ "$PR_BASE_REF" = main ] ||
      batch_fail "PR $n is $PR_STATE with base $PR_BASE_REF"
    [ "$CHECKS" = GREEN ] || batch_fail "PR $n checks=$CHECKS"
    both="$(common_paths "$PR_FILES" "$seen")"
    [ -z "$both" ] || batch_fail "PR $n overlaps an earlier PR in the batch on: $both"
    seen="$seen"$'\n'"$PR_FILES"
    case $'\n'"$PR_FILES" in *$'\n'apps/web/*) web=1 ;; esac
    HEADS+=("$PR_HEAD")
  done
  base="$(git rev-parse origin/main)"
  WT="$(dirname "$(repo_root)")/pl-wt/ROOT-BATCH-$(date -u +%Y%m%dT%H%M%SZ)"

  if ((DRY_RUN)); then
    echo "would run: git worktree add --detach $WT $base"
    for i in "${!PRS[@]}"; do echo "would run: git -C $WT merge --no-edit ${HEADS[$i]}"; done
    echo "would run: (cd $WT && HF_HUB_OFFLINE=1 $MAKE_CMD check)"
    if ((web)); then echo "would run: (cd $WT && HF_HUB_OFFLINE=1 $MAKE_CMD web-test)"; fi
    for i in "${!PRS[@]}"; do
      echo "would run: gh pr merge ${PRS[$i]} --squash --match-head-commit ${HEADS[$i]}"
    done
    echo "would run: git worktree remove $WT"
    echo "DRY-RUN batch ${PRS[*]} base=$(short "$base"): nothing changed"
    return
  fi

  git worktree add -q --detach "$WT" "$base" || batch_fail "git worktree add $WT failed"
  WT_STATE="kept: $WT"
  for i in "${!PRS[@]}"; do
    if ! git -C "$WT" merge -q --no-edit "${HEADS[$i]}"; then
      git -C "$WT" merge --abort || true
      if git worktree remove "$WT"; then WT_STATE=removed; fi
      batch_fail "PR ${PRS[$i]} does not merge cleanly onto the batch"
    fi
  done
  tree="$(git -C "$WT" rev-parse 'HEAD^{tree}')"
  mkdir -p "$WT/.batch-logs"
  run_make check "$WT/.batch-logs/make-check.log" || batch_fail "make check failed"
  if ((web)); then
    run_make web-test "$WT/.batch-logs/make-web-test.log" || batch_fail "make web-test failed"
  fi

  expected="$base"
  for i in "${!PRS[@]}"; do
    git fetch -q origin main || batch_fail "git fetch origin main failed"
    cur="$(git rev-parse origin/main)"
    [ "$cur" = "$expected" ] ||
      batch_fail "main moved to $(short "$cur") (expected $(short "$expected")) before PR ${PRS[$i]}"
    merge_and_confirm "${PRS[$i]}" "${HEADS[$i]}" || batch_fail "$FAIL_REASON"
    MERGED_PRS="$MERGED_PRS,${PRS[$i]}"
    MERGED_LIST="${MERGED_LIST:+$MERGED_LIST,}${PRS[$i]}->$(short "$MERGE_SHA")"
    expected="$MERGE_SHA"
  done
  git fetch -q origin main || batch_fail "git fetch origin main failed"
  final="$(git rev-parse 'origin/main^{tree}')"
  [ "$final" = "$tree" ] ||
    batch_fail "origin/main tree $(short "$final") is not the tested tree $(short "$tree")"
  if git worktree remove "$WT"; then
    WT_STATE=removed
  else
    echo "warning: git worktree remove $WT failed; left in place" >&2
  fi
  reminder
  echo "BATCH OK tree=$(short "$tree") merged=$MERGED_LIST worktree=$WT_STATE"
}

main() {
  local mode="${1:-}" arg
  [ -n "$mode" ] || usage
  shift
  DRY_RUN=0 ALLOW_DISJOINT=0
  local prs=()
  for arg in "$@"; do
    case "$arg" in
      --dry-run) DRY_RUN=1 ;;
      --allow-disjoint)
        [ "$mode" = merge ] || usage
        ALLOW_DISJOINT=1
        ;;
      *[!0-9]* | "") usage ;;
      *) prs+=("$arg") ;;
    esac
  done
  case "$mode" in
    check | merge | update)
      [ "${#prs[@]}" = 1 ] || usage
      "cmd_$mode" "${prs[0]}"
      ;;
    batch)
      [ "${#prs[@]}" -ge 1 ] || usage
      cmd_batch "${prs[@]}"
      ;;
    *) usage ;;
  esac
}

main "$@"
