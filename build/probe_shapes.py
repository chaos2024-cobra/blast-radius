#!/usr/bin/env python3
"""Probe v8 selector behavior on the 6 problem shapes from the task."""
import contextlib
import difflib
import importlib.util
import io
import json
import sys
from pathlib import Path

WORK = Path("/home/z/my-project/work")
REPO = WORK / "sqlglot/repo"
TESTS = json.loads((WORK / "blast-radius-sample/sample/tests.json").read_text())["tests"]
N2I = {t["number"]: t["id"] for t in TESTS}


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
    """Unified diff in git format with 3 lines of context."""
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="", n=3)
    body = "\n".join(diff) + "\n"
    # unified_diff emits --- +++ with dummy names; rewrite to git style
    lines = body.splitlines()
    out = [f"diff --git a/{path} b/{path}"]
    for i, l in enumerate(lines):
        if l.startswith("--- "):
            out.append(f"--- a/{path}")
        elif l.startswith("+++ "):
            out.append(f"+++ b/{path}")
        else:
            out.append(l)
    return "\n".join(out) + "\n"


def add_line_after(path, lineno, text):
    """Insert text after given 1-based line; return patch."""
    src = (REPO / path).read_text()
    lines = src.splitlines(keepends=True)
    new = lines[:lineno] + [text + "\n"] + lines[lineno:]
    return make_patch(path, [l.rstrip("\n") for l in lines],
                      [l.rstrip("\n") for l in new])


def main():
    sel_mod = load(WORK / "submission-v8/selector.py", "v8")
    sel = sel_mod.Selector()
    F = {t["file"]: t["id"] for t in TESTS}

    # --- probe 1: '#' add inside a multi-line string span (dialect.py) ---
    # docspans sqlglot.dialects.dialect has [477,483] etc — pick line 480 (inside span)
    p = add_line_after("sqlglot/dialects/dialect.py", 480, "#")
    s = sel.select(p, TESTS)
    print(f"P1 '#' inside string span dialect.py:480  -> {len(s)} tests")

    # --- probe 1b: '#' add at a normal code line (comment-only hunk) ---
    p = add_line_after("sqlglot/dialects/dialect.py", 200, "# comment")
    s = sel.select(p, TESTS)
    print(f"P1b '#' normal comment dialect.py:200    -> {len(s)} tests")

    # --- probe 2: docstring delete + code add ---
    src = (REPO / "sqlglot/dialects/dialect.py").read_text()
    lines = src.splitlines()
    # find a docstring: [156,157] span — delete line 156, add live code
    new = [l if i != 155 else "x_var = 1" for i, l in enumerate(lines)]
    p = make_patch("sqlglot/dialects/dialect.py", lines, new)
    s = sel.select(p, TESTS)
    print(f"P2 docstring del + code add              -> {len(s)} tests")

    # --- probe 3: pure-add statement at start of a function ---
    # find function start via symbols
    import ast
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "normalize":
            fn = node
            break
    if fn:
        new = lines[:fn.lineno] + ["    raise SystemExit(1)"] + lines[fn.lineno:]
        p = make_patch("sqlglot/dialects/dialect.py", lines, new)
        s = sel.select(p, TESTS)
        print(f"P3 pure-add at dialect.py:{fn.lineno} (normalize) -> {len(s)} tests")

    # --- probe 4: edit tests/dialects/test_dialect.py ---
    tsrc = (REPO / "tests/dialects/test_dialect.py").read_text()
    tl = tsrc.splitlines()
    new = [l if i != 20 else l + " x = 1" for i, l in enumerate(tl)]
    p = make_patch("tests/dialects/test_dialect.py", tl, new)
    s = sel.select(p, TESTS)
    own = sum(1 for t in s if t in set(
        x["id"] for x in TESTS if x["file"] == "tests/dialects/test_dialect.py"))
    print(f"P4 edit test_dialect.py                  -> {len(s)} tests "
          f"({own} from test_dialect.py itself)")

    # --- probe 5: edit sqlglot/typing/hive.py ---
    ysrc = (REPO / "sqlglot/typing/hive.py").read_text()
    yl = ysrc.splitlines()
    new = [l if i != 30 else l + " # x" for i, l in enumerate(yl)]
    new[30] = "x_y_z = 1"
    p = make_patch("sqlglot/typing/hive.py", yl, new)
    s = sel.select(p, TESTS)
    has_typing = F["tests/test_typing.py"] in s
    print(f"P5 edit sqlglot/typing/hive.py           -> {len(s)} tests, "
          f"test_typing selected: {has_typing}")

    # --- probe 6: rename + other file (no +++/--- for the renamed file) ---
    p = ("diff --git a/sqlglot/helper.py b/sqlglot/new_helper.py\n"
         "similarity index 98%\n"
         "rename from sqlglot/helper.py\n"
         "rename to sqlglot/new_helper.py\n")
    p2 = add_line_after("sqlglot/dialects/dialect.py", 480, "#")
    s = sel.select(p + p2, TESTS)
    print(f"P6 rename+other                          -> {len(s)} tests (of {len(TESTS)})")

    # --- probe 6b: mode change ---
    p3 = ("diff --git a/sqlglot/helper.py b/sqlglot/helper.py\n"
          "old mode 100644\n"
          "new mode 100755\n") + p2
    s = sel.select(p3, TESTS)
    print(f"P6b mode change+other                    -> {len(s)} tests")


if __name__ == "__main__":
    main()
