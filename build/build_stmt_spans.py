#!/usr/bin/env python3
"""Build STATEMENT-granular maps from the pinned tree:
- stmt_spans.json: {mod: [[start_line, end_line], ...]} every executable statement's
  line span (if/while conditions span their whole header incl. continuation lines).
- Reused to convert a mutated line L -> its statement's line set, so that:
  * line_tests lookup: tests executing ANY line of the statement
  * pool children: children executing ANY line of the statement
"""
import ast
import json
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
OUT = Path("/home/z/my-project/work/maps/stmt_spans.json")

spans = {}
for py in REPO.glob("sqlglot/**/*.py"):
    mod = str(py.relative_to(REPO))[:-3].replace("/", ".")
    try:
        tree = ast.parse(py.read_text())
    except SyntaxError:
        continue
    sl = []

    def add(node):
        try:
            sl.append([node.lineno, node.end_lineno])
        except AttributeError:
            pass

    def walk(node):
        # statements: the units whose execution can observe a mutation inside them
        if isinstance(node, (ast.stmt,)) and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node)
        # boolean ops / conditions: a mutated operand changes evaluation of the whole op
        if isinstance(node, (ast.BoolOp, ast.IfExp, ast.If, ast.While)):
            add(node)
        for ch in ast.iter_child_nodes(node):
            walk(ch)

    walk(tree)
    if sl:
        spans[mod] = sl

OUT.write_text(json.dumps(spans))
print(f"modules: {len(spans)}, total spans: {sum(len(v) for v in spans.values())}")
