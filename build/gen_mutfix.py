#!/usr/bin/env python3
"""Generate mutation patches for the fix verification harness (categories a-e).

(a) '#' and blank-line adds at every line of dialect.py and duckdb.py,
    including inside multi-line strings  -> 2 sub-variants ('#', ''), both labeled
(b) docstring edit + added live code
(c) pure-add statement at the start of each function
(d) edits to tests/dialects/test_dialect.py
(e) edits to sqlglot/typing/*.py

Writes patches to work/mutfix/<cat>/<name>.patch. Sampling is deterministic.
"""
import ast
import difflib
import random
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
OUT = Path("/home/z/my-project/work/mutfix")
OUT.mkdir(parents=True, exist_ok=True)
rng = random.Random(42)


def string_spans(src):
    """Multi-line string spans (incl. f-strings): ast.Constant + JoinedStr."""
    tree = ast.parse(src)
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            if isinstance(node, ast.Constant) and not isinstance(node.value, str):
                continue
            if getattr(node, "end_lineno", None) and node.end_lineno > node.lineno:
                spans.append((node.lineno, node.end_lineno))
    return spans


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
    return "diff --git a/%s b/%s\n" % (path, path) + "\n".join(body) + "\n"


def write(cat, name, patch):
    if patch is None:
        return
    d = OUT / cat
    d.mkdir(exist_ok=True)
    (d / f"{name}.patch").write_text(patch)


def add_after(lines, lineno, text):
    """lines is a list WITHOUT line endings; insert text after 1-based lineno."""
    return lines[:lineno] + [text] + lines[lineno:]


# ---------------- (a) '#' and blank adds in dialect.py + duckdb.py ----------------
A_STRIDE_OUTSIDE = 25   # sample of non-string lines
for fname, short in [("sqlglot/dialects/dialect.py", "dialect"),
                     ("sqlglot/generators/duckdb.py", "duckdb")]:
    src = (REPO / fname).read_text()
    lines = src.splitlines()
    spans = string_spans(src)
    in_span = set()
    for s, e in spans:
        in_span.update(range(s, e + 1))
    n = len(lines)
    # every line inside spans (insert AFTER each span line, 1..n-1);
    # span insertion at line L means text becomes part of the string
    span_lines = [l for l in range(1, n) if l in in_span and l + 1 <= n]
    # stride sample of the other lines
    other_lines = [l for l in range(1, n) if l not in in_span]
    sample_other = other_lines[::A_STRIDE_OUTSIDE]
    chosen = span_lines + sample_other
    for l in chosen:
        loc = "in" if l in in_span else "out"
        for variant, text in [("#", "#"), ("blank", "")]:
            name = f"{short}_{loc}_L{l}_{variant}"
            write("a", name, make_patch(fname, lines, add_after(lines, l, text)))

# ---------------- (b) docstring edit + added code ----------------
B_FILES = [
    "sqlglot/dialects/dialect.py", "sqlglot/generators/duckdb.py",
    "sqlglot/lineage.py", "sqlglot/helper.py", "sqlglot/time.py",
    "sqlglot/generators/hive.py", "sqlglot/transforms.py", "sqlglot/parser.py",
    "sqlglot/generator.py", "sqlglot/expressions/core.py",
]
B_MAX_PER_FILE = 6
for fname in B_FILES:
    p = REPO / fname
    if not p.exists():
        continue
    src = p.read_text()
    lines = src.splitlines()
    tree = ast.parse(src)
    docstrings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = node.body
            if (b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                docstrings.append((b[0].lineno, b[0].end_lineno, getattr(node, "name", "<module>")))
    docstrings.sort()
    for i, (s, e, nm) in enumerate(docstrings[:B_MAX_PER_FILE]):
        # variant 1: replace a docstring line with live code
        new = [l if j != s - 1 else "zz_live_code = 1" for j, l in enumerate(lines)]
        write("b", f"doc_code_{Path(fname).stem}_{i}_{nm[:24]}", make_patch(fname, lines, new))
        # variant 2: delete first docstring line + append a live line after the span
        new = [l for j, l in enumerate(lines) if j != s - 1]
        write("b", f"doc_deladd_{Path(fname).stem}_{i}_{nm[:24]}",
              make_patch(fname, lines, add_after(new, e - 1, "zz_live_code = 2")))

# ---------------- (c) pure-add statement at start of each function ----------------
C_MAX = 60
count = 0
all_fns = []
for p in sorted((REPO / "sqlglot").rglob("*.py")):
    rel = str(p.relative_to(REPO))
    src = p.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and count < C_MAX * 4:
            all_fns.append((rel, node.name, node.body[0].lineno, src.splitlines()))
            count += 1
rng.shuffle(all_fns)
for rel, nm, lineno, lines in all_fns[:C_MAX]:
    indent = "    "
    write("c", f"pureadd_{Path(rel).stem}_{nm[:30]}",
          make_patch(rel, lines, add_after(lines, lineno - 1, indent + "zz_raise = 1")))

# ---------------- (d) edits to tests/dialects/test_dialect.py ----------------
D = "tests/dialects/test_dialect.py"
src = (REPO / D).read_text()
lines = src.splitlines()
tree = ast.parse(src)
n_funcs = 0
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        first = node.body[0].lineno
        # insert live code as first statement of the method
        write("d", f"td_func_{node.name[:30]}",
              make_patch(D, lines, add_after(lines, first - 1, "        zz_live = 1")))
        n_funcs += 1
        if n_funcs >= 20:
            break
# module-level edit (top of file, after imports)
write("d", "td_module_top", make_patch(D, lines, add_after(lines, 10, "zz_module_live = 1")))

# ---------------- (e) edits to sqlglot/typing/*.py ----------------
for p in sorted((REPO / "sqlglot/typing").glob("*.py")):
    rel = str(p.relative_to(REPO))
    if rel.endswith("__init__.py"):
        continue
    src = p.read_text()
    lines = src.splitlines()
    tree = ast.parse(src)
    # find EXPRESSION_METADATA dict start
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "EXPRESSION_METADATA" for t in node.targets):
            ln = node.lineno
            write("e", f"typ_meta_{p.stem}", make_patch(
                rel, lines, add_after(lines, ln - 1, '    "zz": {"annotator": None},')))
            break
    # plain module-level live add
    write("e", f"typ_live_{p.stem}", make_patch(rel, lines, add_after(lines, 5, "zz_typing_live = 1")))

# summary
for d in sorted(OUT.iterdir()):
    print(d.name, len(list(d.glob("*.patch"))), "patches")
