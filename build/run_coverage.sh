#!/bin/bash
# Run the pinned test suite under per-test coverage.
# Produces work/cov/.coverage (sqlite). SKIP_INTEGRATION=0 matches how the
# organizers labeled failing tests.
set -e
REPO="${1:-/home/z/my-project/work/sqlglot/repo}"
HERE="$(cd "$(dirname "$0")" && pwd)"
COVDIR="$HERE/cov"
mkdir -p "$COVDIR"
cd "$REPO"
export SKIP_INTEGRATION=0
export COVERAGE_FILE="$COVDIR/.coverage"
rm -f "$COVERAGE_FILE"
python3 -m coverage run --rcfile="$HERE/.coveragerc" -m pytest tests \
  -q -p no:cacheprovider --timeout=120 > "$COVDIR/pytest.log" 2>&1
echo "coverage done"
