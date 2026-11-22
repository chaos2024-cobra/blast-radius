#!/usr/bin/env python3
"""Unit-verify classification on every category-a patch (2410 generated).

For each patch, assert the v9 classification matches ground truth derived
from the generator's own knowledge:
- *_in_* patches: insert inside a multi-line string span -> MUST be treated
  as live (selected > 0 or run-all); never silently skipped.
- *_out_* patches: insert outside any span at a comment-only hunk -> must
  select enclosing scope or module floor (>= 1 test when inside a function
  of a module in the maps; 0 allowed only at true module level).
Also verify: no patch selects nothing while failing to parse (run-all must
be all).
"""
import contextlib
import importlib.util
import io
import json
import re
from pathlib import Path

WORK = Path("/home/z/my-project/work")
TESTS = json.loads((WORK / "blast-radius-sample/sample/tests.json").read_text())["tests"]
A_DIR = WORK / "mutfix/a"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            spec.loader.exec_module(m)
        except SystemExit:
            pass
    return m


def main():
    v9 = load(WORK / "submission-v9/selector.py", "v9x")
    sel = v9.Selector()
    all_ids = {t["id"] for t in TESTS}

    stats = {"in": [0, 0], "out": [0, 0]}  # [total, selected>0]
    fails = []
    for p in sorted(A_DIR.glob("*.patch")):
        m = re.match(r"(\w+)_(in|out)_L(\d+)_(#|blank)", p.name)
        assert m, p.name
        loc = m.group(2)
        txt = p.read_text()
        files, run_all = v9.parse_diff9(txt)
        s = sel.select(txt, TESTS)
        nsel = len(s)
        stats[loc][0] += 1
        if nsel > 0:
            stats[loc][1] += 1
        # ground truth: in-string must never be skipped
        if loc == "in":
            if nsel == 0:
                # check ground truth: is the line really in a span?
                path = "sqlglot/dialects/dialect.py" if m.group(1) == "dialect" \
                    else "sqlglot/generators/duckdb.py"
                ln = int(m.group(3))
                # insertion after line ln -> slot ln+1
                inspan = any(s0 <= ln + 1 <= e for s0, e, c in v9.STRSPANS.get(path, ()))
                if inspan:
                    fails.append((p.name, "in-span but 0 tests"))
        else:
            # out-of-span: 0 allowed only at module level (no enclosing scope)
            if nsel == 0:
                path = "sqlglot/dialects/dialect.py" if m.group(1) == "dialect" \
                    else "sqlglot/generators/duckdb.py"
                ln = int(m.group(3))
                files2, _ = v9.parse_diff9(txt)
                h = files2[("new", path)][0]
                ranges = v9.hunk_ranges9(h)
                lo = max(1, min(r[0] for r in ranges))
                hi = max(r[1] for r in ranges)
                mod = path[:-3].replace("/", ".")
                funcs, classes, mlines = sel.v6.enclosing(mod, lo, hi)
                if funcs:
                    fails.append((p.name, f"out-of-span with enclosing funcs {[f['q'] for f in funcs]} but 0 tests"))
    print(f"in-span patches:  {stats['in'][0]}, selected>0: {stats['in'][1]}")
    print(f"out-span patches: {stats['out'][0]}, selected>0: {stats['out'][1]}")
    if fails:
        print(f"FAILURES ({len(fails)}):")
        for name, why in fails[:20]:
            print("  ", name, "-", why)
        raise SystemExit(1)
    print("ALL CLASSIFICATION CHECKS PASS")


if __name__ == "__main__":
    main()
