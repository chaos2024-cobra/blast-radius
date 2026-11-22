#!/usr/bin/env bash
# Label a directory of .patch files with real full-suite pytest runs.
# Usage: bash label_patches.sh <patch_dir> <out_dir> [filter_glob]
# Skips patches already labeled (non-empty out json). 2 xdist workers.
set -u
REPO=/home/z/my-project/work/sqlglot/repo
VENV=/home/z/my-project/work/labelwork/venv
WORK=/tmp/labelwork
PATCHES=${1:?patch dir}
OUT=${2:?out dir}
mkdir -p "$OUT" "$WORK"

for p in "$PATCHES"/*.patch; do
  name=$(basename "$p" .patch)
  out="$OUT/$name.json"
  [ -s "$out" ] && { echo "skip $name"; continue; }
  rm -rf "$WORK/tree"
  git -C "$REPO" worktree prune >/dev/null 2>&1
  git -C "$REPO" worktree add --detach "$WORK/tree" eb11aec4b -q 2>/dev/null || { echo "$name: worktree fail"; continue; }
  if ! git -C "$WORK/tree" apply --check "$p" 2>/dev/null; then
    echo "{\"patch_failed\": true}" > "$out"
    git -C "$REPO" worktree remove --force "$WORK/tree" >/dev/null 2>&1
    echo "$name: PATCH FAILED"; continue
  fi
  git -C "$WORK/tree" apply "$p" 2>/dev/null
  cd "$WORK/tree"
  SKIP_INTEGRATION=0 PYTHONPATH="$WORK/tree" timeout 900 "$VENV/bin/python" -m pytest tests \
    -q -p no:cacheprovider -n 2 --dist loadfile \
    --json-report --json-report-file="$WORK/report.json" >/dev/null 2>&1
  "$VENV/bin/python" - "$WORK/report.json" "$out" <<'EOF'
import json, sys
rep, out = sys.argv[1], sys.argv[2]
try:
    r = json.load(open(rep))
except Exception:
    json.dump({"run_failed": True}, open(out, "w")); sys.exit()
tests = r.get("tests", [])
failing = sorted({t["nodeid"] for t in tests if t["outcome"] in ("failed", "error")})
json.dump({"failing": failing, "n": len(tests)}, open(out, "w"))
EOF
  n=$("$VENV/bin/python" -c "import json;print(len(json.load(open('$out')).get('failing',[])))" 2>/dev/null)
  echo "$name: failing=$n"
  git -C "$REPO" worktree remove --force "$WORK/tree" >/dev/null 2>&1
done
echo DONE
