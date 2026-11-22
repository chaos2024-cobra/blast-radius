#!/usr/bin/env python3
"""Verify v9 selector on the 6 problem shapes + quick regression checks."""
import contextlib
import difflib
import importlib.util
import io
import json
import re
from pathlib import Path

WORK = Path("/home/z/my-project/work")
REPO = WORK / "sqlglot/repo"
TESTS = json.loads((WORK / "blast-radius-sample/sample/tests.json").read_text())["tests"]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            spec.loader.exec_module(m)
        except SystemExit:
            pass
    return m


def make_patch(path, old_lines, new_lines):
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))
    if not diff:
        return None
    body = []
    for l in diff:
        if l.startswith("--- "):
            body.append(f"--- a/{path}")
        elif l.startswith("+++ "):
            body.append(f"+++ b/{path}")
        else:
            body.append(l)
    return f"diff --git a/{path} b/{path}\n" + "\n".join(body) + "\n"


def add_after(lines, lineno, text):
    return lines[:lineno] + [text] + lines[lineno:]


def main():
    sel = load(WORK / "submission-v9/selector.py", "v9").Selector()
    all_ids = {t["id"] for t in TESTS}
    file_of = {t["id"]: t["file"] for t in TESTS}

    results = {}

    # P1: '#' inside a value-string span (dialect.py 1135-1136) and a noop span
    src = (REPO / "sqlglot/dialects/dialect.py").read_text()
    lines = src.splitlines()
    p = make_patch("sqlglot/dialects/dialect.py", lines, add_after(lines, 1135, "#"))
    s = sel.select(p, TESTS)
    results["P1a # in value string (dialect 1135)"] = len(s)

    p = make_patch("sqlglot/dialects/dialect.py", lines, add_after(lines, 480, "#"))
    s = sel.select(p, TESTS)
    results["P1b # in noop span (dialect 480)"] = len(s)

    # duckdb value span line (2053-2066)
    dsrc = (REPO / "sqlglot/generators/duckdb.py").read_text()
    dl = dsrc.splitlines()
    p = make_patch("sqlglot/generators/duckdb.py", dl, add_after(dl, 2060, "#"))
    s = sel.select(p, TESTS)
    results["P1c # in duckdb value string"] = len(s)

    # P1d: plain comment add at a code line
    p = make_patch("sqlglot/dialects/dialect.py", lines, add_after(lines, 200, "# c"))
    s = sel.select(p, TESTS)
    results["P1d # plain comment (dialect 200)"] = len(s)

    # P2: docstring delete + code add
    new = [l if i != 155 else "zz = 1" for i, l in enumerate(lines)]
    p = make_patch("sqlglot/dialects/dialect.py", lines, new)
    s = sel.select(p, TESTS)
    results["P2 docstring-del + code-add"] = len(s)

    # P2b: docstring line replaced with another docstring line (safe)
    new = [l if i != 155 else "    Case-insensitive regardless of quotes." for i, l in enumerate(lines)]
    p = make_patch("sqlglot/dialects/dialect.py", lines, new)
    s = sel.select(p, TESTS)
    results["P2b docstring-text-only edit"] = len(s)

    # P3: pure-add at start of function (normalize, line 2598)
    import ast
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "normalize")
    new = lines[:fn.lineno] + ["    zz = 1"] + lines[fn.lineno:]
    p = make_patch("sqlglot/dialects/dialect.py", lines, new)
    s = sel.select(p, TESTS)
    results[f"P3 pure-add at dialect.py:{fn.lineno}"] = len(s)

    # P4: edit tests/dialects/test_dialect.py
    tsrc = (REPO / "tests/dialects/test_dialect.py").read_text()
    tl = tsrc.splitlines()
    new = [l if i != 20 else l + " zz" for i, l in enumerate(tl)]
    p = make_patch("tests/dialects/test_dialect.py", tl, new)
    s = sel.select(p, TESTS)
    dialect_files = {f for f in {file_of[i] for i in s} if f.startswith("tests/dialects/")}
    results["P4 test_dialect.py edit"] = len(s)
    results["P4 dialect files covered"] = len(dialect_files)

    # P5: sqlglot/typing/hive.py live edit
    ysrc = (REPO / "sqlglot/typing/hive.py").read_text()
    yl = ysrc.splitlines()
    new = [l if i != 30 else "zz = 1" for i, l in enumerate(yl)]
    p = make_patch("sqlglot/typing/hive.py", yl, new)
    s = sel.select(p, TESTS)
    results["P5 typing/hive.py edit (test_typing in?)"] = (
        "tests/test_typing.py::TestTyping::test_no_redundant_expression_metadata" in s)

    # P5b: sqlglot/generators/hive.py edit (test_time reads CANONICAL_TIME_FORMAT)
    hsrc = (REPO / "sqlglot/generators/hive.py").read_text()
    hl = hsrc.splitlines()
    new = [l if i != 30 else l + " zz" for i, l in enumerate(hl)]
    p = make_patch("sqlglot/generators/hive.py", hl, new)
    s = sel.select(p, TESTS)
    tt = [i for i in s if "test_time" in i]
    results["P5b generators/hive.py edit -> test_time tests"] = len(tt)

    # P6: rename + other
    p6 = ("diff --git a/sqlglot/helper.py b/sqlglot/new_helper.py\n"
          "similarity index 98%\n"
          "rename from sqlglot/helper.py\n"
          "rename to sqlglot/new_helper.py\n")
    p1 = make_patch("sqlglot/dialects/dialect.py", lines, add_after(lines, 480, "#"))
    s = sel.select(p6 + p1, TESTS)
    results["P6 rename+other -> run-all"] = len(s) == len(all_ids)

    # P6b: mode change
    p6b = ("diff --git a/sqlglot/helper.py b/sqlglot/helper.py\n"
           "old mode 100644\n"
           "new mode 100755\n") + p1
    s = sel.select(p6b, TESTS)
    results["P6b mode change -> run-all"] = len(s) == len(all_ids)

    # P6c: binary
    p6c = ("diff --git a/logo.png b/logo.png\n"
           "Binary files a/logo.png and b/logo.png differ\n") + p1
    s = sel.select(p6c, TESTS)
    results["P6c binary+other -> run-all"] = len(s) == len(all_ids)

    # P7: unchanged behavior — comment-only on a non-sqlglot .py file
    p = make_patch("setup.py", ["x = 1"], ["x = 1", "# c"])
    s = sel.select(p, TESTS)
    results["P7 setup.py comment (run-all)"] = len(s) == len(all_ids)

    for k, v in results.items():
        print(f"{'PASS' if v not in (0, False) else 'FAIL':4} {k}: {v}")


if __name__ == "__main__":
    main()
