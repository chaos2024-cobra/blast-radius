#!/usr/bin/env python3
"""Build the three new maps for v9 from the pinned sqlglot commit:

1. strspans: module -> [[s, e, cls], ...] line spans of every multi-line
   string literal (docstring=0, noop expr=1, value=2). Built with ast over
   Constant and JoinedStr nodes (f-strings included).
2. test_import_closure: tests/<path>.py -> [tests/<path>.py, ...] transitive
   importers among the test files (who breaks if this file breaks).
3. read_map: source path -> [test ids] for tests that read sources as text
   or compare __code__ (tests/test_typing.py, test_sqlglotc.py), derived by
   static scan of the tests at the pinned commit.

All inputs are the pinned tree only. Output: work/maps/v9_maps.json
"""
import ast
import json
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
TESTS_JSON = Path("/home/z/my-project/work/blast-radius-sample/sample/tests.json")
OUT = Path("/home/z/my-project/work/maps/v9_maps.json")


def string_spans_cls(src):
    """[(s, e, cls)] for multi-line string literals."""
    tree = ast.parse(src)
    doc_ids, noop_ids = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = node.body
            if (b and isinstance(b[0], ast.Expr)
                    and isinstance(b[0].value, (ast.Constant, ast.JoinedStr))):
                v = b[0].value
                if isinstance(v, ast.Constant) and not isinstance(v.value, str):
                    continue
                doc_ids.add(id(v))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            v = node.value
            if isinstance(v, ast.Constant) and not isinstance(v.value, str):
                continue
            if id(v) not in doc_ids:
                noop_ids.add(id(v))
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            if isinstance(node, ast.Constant) and not isinstance(node.value, str):
                continue
            if getattr(node, "end_lineno", None) and node.end_lineno > node.lineno:
                cls = 0 if id(node) in doc_ids else (1 if id(node) in noop_ids else 2)
                spans.append([node.lineno, node.end_lineno, cls])
    spans.sort()
    return spans


def build_strspans():
    out = {}
    for p in sorted(REPO.glob("sqlglot/**/*.py")) + sorted(REPO.glob("sqlglotc/**/*.py")):
        rel = str(p.relative_to(REPO))
        try:
            src = p.read_text()
            spans = string_spans_cls(src)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            spans = [[1, 10**6, 2]]  # unknown -> treat every line as live value string
        if spans:
            out[rel] = spans
    return out


def resolve_import(from_file, module, level):
    """Module name -> file path relative to repo, or None."""
    if level:  # relative import: resolve against the importing file
        base = Path(from_file).parent
        for _ in range(level - 1):
            base = base.parent
        cand = base / Path(*module.split(".")) if module else base
    else:  # absolute import: resolve from the repo root
        cand = Path(*module.split(".")) if module else Path(".")
    for f in [cand.with_suffix(".py"), cand / "__init__.py"]:
        if (REPO / f).exists():
            return str(f)
    return None


def build_test_closure():
    """tests file -> transitive importers (test files that import it)."""
    test_files = [str(p.relative_to(REPO)) for p in sorted(REPO.glob("tests/**/*.py"))]
    tset = set(test_files)
    edges = {}  # file -> set of imported test files
    for f in test_files:
        p = REPO / f
        try:
            tree = ast.parse(p.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    r = resolve_import(f, a.name, 0)
                    if r in tset and r != f:
                        deps.add(r)
            elif isinstance(node, ast.ImportFrom):
                r = resolve_import(f, node.module, node.level)
                if r in tset and r != f:
                    deps.add(r)
                # 'from X import Y' where Y is itself a module file
                if node.module:
                    for a in node.names:
                        r2 = resolve_import(f, node.module + "." + a.name, 0)
                        if r2 in tset and r2 != f:
                            deps.add(r2)
        if deps:
            edges[f] = deps
    # reverse: imported -> importers
    rev = {}
    for f, deps in edges.items():
        for d in deps:
            rev.setdefault(d, set()).add(f)
    # transitive closure over importers
    closure = {}
    for f in test_files:
        seen, stack = set(), [f]
        while stack:
            x = stack.pop()
            for imp in rev.get(x, ()):
                if imp not in seen:
                    seen.add(imp)
                    stack.append(imp)
        if seen:
            closure[f] = sorted(seen)
    return closure


def build_read_map():
    """source path -> [test ids] for tests that read source files as text.

    Static scan of the pinned tests for: read_text/read/readlines on paths
    derived from __file__, pkgutil.iter_modules, runpy.run_path, and __code__
    comparisons. Mapping is by module directory (sqlglot/typing/) or explicit
    path constant (sqlglotc/setup.py).
    """
    tests = json.loads(TESTS_JSON.read_text())["tests"]
    out = {}  # source path -> set(test ids)
    for t in tests:
        f = REPO / t["file"]
        if not f.exists():
            continue
        try:
            src = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        read_src = False
        # 1) runpy.run_path of a repo-relative path
        for m in ast.walk(ast.parse(src)):
            pass
        # text scan (robust for this pinned tree)
        if "runpy" in src and "sqlglotc" in src:
            for p in sorted((REPO / "sqlglotc").rglob("*")):
                if p.is_file():
                    rel = str(p.relative_to(REPO))
                    out.setdefault(rel, set()).add(t["id"])
        if "pkgutil" in src and "sqlglot.typing" in src:
            for p in sorted((REPO / "sqlglot/typing").glob("*.py")):
                rel = str(p.relative_to(REPO))
                out.setdefault(rel, set()).add(t["id"])
        if "__code__" in src and "sqlglot.typing" in src:
            for p in sorted((REPO / "sqlglot/typing").glob("*.py")):
                rel = str(p.relative_to(REPO))
                out.setdefault(rel, set()).add(t["id"])
        if "read_text" in src:
            read_src = True
        if read_src and "sqlglot" in src:
            # conservative: map every path constant in the file that exists in repo
            import re as _re
            for m2 in _re.finditer(r'["\']([\w./-]+\.py)["\']', src):
                rel = m2.group(1).lstrip("./")
                if (REPO / rel).exists() and rel.startswith(("sqlglot", "tests")):
                    out.setdefault(rel, set()).add(t["id"])
    return {k: sorted(v) for k, v in out.items()}


def main():
    strspans = build_strspans()
    closure = build_test_closure()
    read_map = build_read_map()
    data = {"strspans": strspans, "test_closure": closure, "read_map": read_map}
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print("strspans modules:", len(strspans))
    nd = {m: [s for s in v if s[2] == 2] for m, v in strspans.items()}
    print("modules with value-string spans:", sum(1 for v in nd.values() if v))
    print("test_closure files:", len(closure))
    top = sorted(closure.items(), key=lambda kv: -len(kv[1]))[:3]
    for f, imps in top:
        print("  ", f, "<-", len(imps), "importers")
    print("read_map paths:", len(read_map))
    for k, v in list(read_map.items())[:12]:
        print("  ", k, "->", v)


if __name__ == "__main__":
    main()
