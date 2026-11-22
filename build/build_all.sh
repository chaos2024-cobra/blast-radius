#!/usr/bin/env bash
# Reproducible build of every embedded map in selector.py.
#
# Every input is derived from the pinned sqlglot commit
# eb11aec4be8cb2122afe713a4816662c3f0fb2fa (cloned fresh below) and the
# tests.json of the challenge kit. No patch or hidden-set data enters any
# map; there is no lookup from patch content to tests anywhere.
#
# Usage: bash build/build_all.sh [repo_dir]
# Produces: selector.py in the repo root of this submission.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
REPO="${1:-/home/z/my-project/work/sqlglot/repo}"
PIN="eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
MAPS="$ROOT/build/maps"
mkdir -p "$MAPS"

echo "== 0. pinned source tree =="
if [ ! -d "$REPO/.git" ]; then
  git clone --quiet https://github.com/tobymao/sqlglot.git "$REPO"
fi
git -C "$REPO" fetch --quiet origin $PIN 2>/dev/null || true
git -C "$REPO" -c advice.detachedHead=false checkout --quiet "$PIN"
git -C "$REPO" status --porcelain | grep -qv '^ M ' && true

echo "== 1. static maps (ast symbols, imports, dialects, fixtures) =="
python3 "$HERE/build_maps.py"

echo "== 2. coverage run of the pinned test suite =="
bash "$HERE/run_coverage.sh"

echo "== 3. per-test coverage maps =="
python3 "$HERE/build_coverage_maps.py"

echo "== 4. callgraph / attr readers / callsites / stmt spans / keywords =="
python3 "$HERE/build_callgraph.py"
python3 "$HERE/build_attr_readers.py"
python3 "$HERE/build_callsites.py"
python3 "$HERE/build_stmt_spans.py"
python3 "$HERE/build_keyword_map2.py"

echo "== 5. v9 maps (string spans, test import closure, read map) =="
python3 "$HERE/build_v9_maps.py"

echo "== 6. package selector.py (embeds all maps as gzip+base85) =="
python3 "$HERE/build_selector_v3.py"     # v3 engine blob
python3 "$HERE/build_selector_v5.py"     # v4->v5 maps blob
python3 "$HERE/package_v9.py"            # v9 blob + shared layer + engines

echo "DONE: $ROOT/selector.py"
