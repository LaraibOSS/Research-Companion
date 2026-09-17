#!/usr/bin/env bash
# Purge unpublished material from ALL git history, before the repo goes public.
#
# Untracking a file cleans the tip, not the repository: `git log --all -- paper/`
# recovers every version from a public clone. This rewrites history so the
# material is genuinely absent.
#
# RUN THIS LAST. It rewrites every commit SHA, so any open pull request is
# invalidated and anyone holding a clone must re-clone (their existing copy
# still contains the purged files). Merge everything first.
#
# Verified on 2026-08-18 against a clone: 826 commits before and after, tip tree
# byte-for-byte identical (767 files, matching hashes), 3014 tests passing.
set -euo pipefail

PATHS=(
  paper
  docs/COMPETITOR_ARCHITECTURES.md
  docs/ARS_COMPARATIVE_ANALYSIS.md
  docs/ARS_INTEGRATION_STUDY.md
)

WORK="${1:-$(mktemp -d)}/purge"
REMOTE="${REMOTE:-git@github.com:LaraibOSS/Research-Companion.git}"

echo "==> fresh mirror clone into $WORK"
git clone --mirror "$REMOTE" "$WORK"
cd "$WORK"

BEFORE=$(git rev-list --count --all)
echo "==> commits before: $BEFORE"

args=()
for p in "${PATHS[@]}"; do args+=(--path "$p"); done

# --prune-empty never is REQUIRED: without it, commits whose only content was
# these paths are deleted outright, silently shrinking the history.
python -m git_filter_repo --invert-paths "${args[@]}" --prune-empty never --force

AFTER=$(git rev-list --count --all)
echo "==> commits after:  $AFTER"
[ "$BEFORE" = "$AFTER" ] || { echo "FAIL: commit count changed ($BEFORE -> $AFTER)"; exit 1; }

for p in "${PATHS[@]}"; do
  n=$(git log --all --oneline -- "$p" | wc -l)
  [ "$n" = "0" ] || { echo "FAIL: $p still referenced by $n commits"; exit 1; }
done
echo "==> all paths purged, no commits lost"

cat <<'NEXT'

Nothing has been pushed. To publish the rewrite:

    cd <workdir>/purge
    git remote add origin <REMOTE>          # filter-repo drops the remote
    git push --force --mirror origin

Then tell every collaborator to re-clone. Old clones still hold the files.
NEXT
