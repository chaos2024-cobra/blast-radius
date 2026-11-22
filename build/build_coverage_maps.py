#!/usr/bin/env python3
"""Turn the coverage data file into per-test maps (session 2).

Reads work/cov/.coverage (sqlite), joins with the AST symbol table, produces:
  test_coverage.json   {test_id: {"modules": {mod: [lines...]}, "funcs": [qualnames...]}}
  line_tests.json      {"mod:line": [test ids covering it]}   (only function-body lines)
  func_tests.json      {"mod:qualname": [test ids executing any of its lines]}
  func_lines.json      {"mod:qualname": [line numbers]}
  module_tests.json    {"mod": [test ids executing any of its lines]}

The test id key is the pytest id WITHOUT the ::subtest suffix (parsed from
coverage contexts, which are pytest test ids).
"""
import ast
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
COV = Path("/home/z/my-project/work/cov/.coverage")
OUT = Path("/home/z/my-project/work/maps")
MAPS = OUT

sys.path.insert(0, str(REPO))


def context_to_test_id(ctx):
    """coverage dynamic_context=test_function produces dotted ids like
    'tests.test_executor.TestExecutor.test_correlated_exists_over_scalar_aggregate'
    (for module-level test functions: 'tests.test_x.test_foo').
    Normalize to pytest ids 'tests/test_x.py::TestC::test_f' as in tests.json."""
    if not ctx.strip():
        return None  # '' = no dynamic context captured (module import etc.)
    parts = ctx.split(".")
    if len(parts) < 3 or not parts[0] == "tests":
        return None
    # file part: tests.<subdirs>.<name> -> tests/<subdirs>/<name>.py
    # find where the test name is: last part is the function; possibly 2nd-to-last
    # is a class. The file is the shortest prefix that exists as a test file.
    return parts  # caller resolves; see below


TEST_FILES = None  # set in main: set of test file paths "tests/....py"


def resolve_ctx(ctx):
    """Dotted coverage context -> pytest id usable as tests.json key."""
    global TEST_FILES
    if not ctx.strip() or "." not in ctx:
        return None
    parts = ctx.split(".")
    if parts[0] != "tests" or TEST_FILES is None:
        return None
    return dotted_to_pytest_id(parts)


def dotted_to_pytest_id(parts):
    """Resolve dotted context parts to (file, class_or_None, func)."""
    func = parts[-1]
    # try class interpretation: [... , file, Class, func] and [..., file, func]
    for cut in (len(parts) - 2, len(parts) - 3):
        if cut < 2:
            continue
        file = "tests/" + "/".join(parts[1:cut]) + ".py"
        if file in TEST_FILES:
            mid = parts[cut:-1]
            if len(mid) == 0:
                return f"{file}::{func}"
            if len(mid) == 1:
                return f"{file}::{mid[0]}::{func}"
    return None


def module_of(path):
    p = Path(path)
    try:
        rel = p.relative_to(REPO)
    except ValueError:
        return None
    s = str(rel.with_suffix("")).replace("/", ".")
    return s if s.startswith("sqlglot.") else None


def main():
    global TEST_FILES
    assert COV.exists(), "coverage data missing"
    TEST_FILES = {str(p.relative_to(REPO)) for p in (REPO / "tests").rglob("test_*.py")}
    con = sqlite3.connect(str(COV))
    cur = con.cursor()

    tests = defaultdict(lambda: {"modules": defaultdict(set), "lines": set()})

    # line_bits if present (line mode), else arcs (branch mode)
    n = cur.execute("select count(*) from line_bits").fetchone()[0]
    test_ids = set()
    if n:
        from coverage.numbits import numbits_to_nums
        cur.execute(
            "select f.path, lb.numbits, c.context from line_bits lb "
            "join file f on lb.file_id=f.id join context c on lb.context_id=c.id"
        )
        for path, numbits, ctx in cur.fetchall():
            mod = module_of(path)
            if not mod:
                continue
            tid = dotted_to_pytest_id(context_parts(ctx)) if False else resolve_ctx(ctx)
            if tid:
                test_ids.add(tid)
                for num in numbits_to_nums(numbits):
                    tests[tid]["modules"][mod].add(num)
                    tests[tid]["lines"].add((mod, num))
        print(f"line_bits rows: {n}")
    else:
        cur.execute(
            "select f.path, a.fromno, a.tono, c.context from arc a "
            "join file f on a.file_id=f.id join context c on a.context_id=c.id"
        )
        rows = cur.fetchall()
        print(f"arc rows: {len(rows)}")
        for path, fr, to, ctx in rows:
            mod = module_of(path)
            if not mod:
                continue
            tid = resolve_ctx(ctx)
            if tid:
                test_ids.add(tid)
                for num in (fr, to):
                    if num > 0:  # -1 = entry/exit pseudo-arcs
                        tests[tid]["modules"][mod].add(num)
                        tests[tid]["lines"].add((mod, num))

    # symbol table for line -> enclosing function
    symbols = json.loads((MAPS / "ast_symbols.json").read_text())
    func_of_line = {}  # mod -> {line: qualname of innermost function}
    func_lines = defaultdict(set)  # (mod, qualname) -> lines
    for mod, entries in symbols.items():
        by_line = {}
        for s in entries:
            if s["kind"] != "function":
                continue
            for ln in range(s["start"], s["end"] + 1):
                by_line[ln] = s["qualname"]  # later (nested) entries overwrite: innermost wins
        func_of_line[mod] = by_line
        for s in entries:
            if s["kind"] == "function":
                func_lines[(mod, s["qualname"])].update(range(s["start"], s["end"] + 1))

    line_tests = defaultdict(list)   # "mod:line" -> [tids]
    func_tests = defaultdict(set)    # "mod:qualname" -> tids
    module_tests = defaultdict(set)  # mod -> tids
    for tid, t in tests.items():
        for mod, lines in t["modules"].items():
            module_tests[mod].add(tid)
            fol = func_of_line.get(mod, {})
            for ln in lines:
                line_tests[f"{mod}:{ln}"].append(tid)
                qn = fol.get(ln)
                if qn:
                    func_tests[f"{mod}:{qn}"].add(tid)

    # only keep function-body lines in line_tests to shrink size? keep all for now
    (MAPS / "test_coverage.json").write_text(json.dumps(
        {tid: {"modules": {m: sorted(ls) for m, ls in t["modules"].items()},
               "n_lines": len(t["lines"])} for tid, t in tests.items()}))
    (MAPS / "line_tests.json").write_text(json.dumps({k: sorted(v) for k, v in line_tests.items()}))
    (MAPS / "func_tests.json").write_text(json.dumps({k: sorted(v) for k, v in func_tests.items()}))
    (MAPS / "func_lines.json").write_text(json.dumps(
        {f"{m}:{qn}": sorted(ls) for (m, qn), ls in func_lines.items()}))
    (MAPS / "module_tests.json").write_text(json.dumps({k: sorted(v) for k, v in module_tests.items()}))

    print(f"tests with coverage: {len(tests)}")
    print(f"distinct (mod,line): {len(line_tests)}")
    print(f"functions with covering tests: {len(func_tests)}")
    print(f"modules executed: {len(module_tests)}")
    for f in ["test_coverage.json", "line_tests.json", "func_tests.json", "func_lines.json", "module_tests.json"]:
        print(f"  {f}: {(MAPS / f).stat().st_size} bytes")


if __name__ == "__main__":
    main()
