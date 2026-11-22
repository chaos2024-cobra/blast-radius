#!/usr/bin/env python3
"""Build the static analysis maps from the pinned sqlglot tree (session 2).

Outputs (all under work/maps/):
  ast_symbols.json   {module: [{name, qualname, kind, start, end, enclosing}]}
                     line -> enclosing symbol resolution data per module
  imports.json       {module: {"modules": [...], "names": [...]}} direct imports
  importers.json     {module: [modules that import it directly]}
  dialect_map.json   {dialect module: [dialect classes defined], inherited class -> module}
  test_imports.json  {test file: [sqlglot modules it imports directly]}

All derived from the pinned commit only (allowed: "Maps built from the pinned
commit (coverage, imports, fixtures)").
"""
import ast
import json
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
OUT = Path("/home/z/my-project/work/maps")
OUT.mkdir(parents=True, exist_ok=True)


def module_name(py: Path) -> str:
    rel = py.relative_to(REPO)
    return str(rel.with_suffix("")).replace("/", ".")


def parse(py: Path):
    try:
        return ast.parse(py.read_text())
    except SyntaxError:
        return None


def build_symbol_table():
    """Every function/class in every module with its line span and lineage."""
    symbols = {}
    for py in sorted(REPO.glob("sqlglot/**/*.py")):
        mod = module_name(py)
        tree = parse(py)
        if tree is None:
            continue
        entries = []

        def walk(node, lineage):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    entries.append({
                        "name": child.name, "qualname": ".".join(lineage + [child.name]),
                        "kind": "function", "start": child.lineno, "end": child.end_lineno,
                        "enclosing": lineage[-1] if lineage else "<module>",
                        "decorators": [ast.dump(d)[:0] or _dec_name(d) for d in child.decorator_list],
                    })
                    walk(child, lineage + [child.name])
                elif isinstance(child, ast.ClassDef):
                    entries.append({
                        "name": child.name, "qualname": ".".join(lineage + [child.name]),
                        "kind": "class", "start": child.lineno, "end": child.end_lineno,
                        "enclosing": lineage[-1] if lineage else "<module>",
                    })
                    walk(child, lineage + [child.name])
                else:
                    walk(child, lineage)

        walk(tree, [])
        symbols[mod] = entries
    return symbols


def _dec_name(d):
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        return d.attr
    if isinstance(d, ast.Call):
        return _dec_name(d.func)
    return "?"


def build_imports(symbols):
    """Direct imports between sqlglot modules + external names each module uses."""
    imports, importers = {}, {}
    for py in sorted(REPO.glob("sqlglot/**/*.py")):
        mod = module_name(py)
        tree = parse(py)
        if tree is None:
            continue
        mods, names = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("sqlglot"):
                    mods.add(node.module)
                    for a in node.names:
                        names.add(f"{node.module}.{a.name}")
                elif node.module:
                    for a in node.names:
                        names.add(f"{node.module}.{a.name}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("sqlglot"):
                        mods.add(a.name)
        imports[mod] = {"modules": sorted(mods), "names": sorted(names)}
        for m in mods:
            importers.setdefault(m, []).append(mod)
    return imports, {k: sorted(set(v)) for k, v in importers.items()}


def build_test_imports():
    """Test file -> sqlglot modules/names it imports directly."""
    out = {}
    for py in sorted((REPO / "tests").glob("**/*.py")):
        rel = str(py.relative_to(REPO))
        if not rel.startswith("tests/") or "fixtures" in rel or "leakcheck" in rel:
            continue
        tree = parse(py)
        if tree is None:
            continue
        mods, names = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("sqlglot"):
                    mods.add(node.module)
                    for a in node.names:
                        names.add(f"{node.module}.{a.name}")
                elif node.module:
                    for a in node.names:
                        names.add(f"{node.module}.{a.name}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("sqlglot"):
                        mods.add(a.name)
        # names imported via `from sqlglot import exp` expanded later by symbol table
        out[rel] = {"modules": sorted(mods), "names": sorted(names)}
    return out


def build_dialect_map():
    """Dialect class -> defining module, and inheritance edges between dialect classes."""
    classes = {}
    edges = []
    for py in sorted(REPO.glob("sqlglot/dialects/*.py")):
        mod = module_name(py)
        tree = parse(py)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = mod
                for base in node.bases:
                    name = None
                    if isinstance(base, ast.Name):
                        name = base.id
                    elif isinstance(base, ast.Attribute):
                        name = base.attr
                    if name:
                        edges.append((node.name, name))
    return classes, edges


def main():
    symbols = build_symbol_table()
    (OUT / "ast_symbols.json").write_text(json.dumps(symbols))
    imports, importers = build_imports(symbols)
    (OUT / "imports.json").write_text(json.dumps(imports))
    (OUT / "importers.json").write_text(json.dumps(importers))
    (OUT / "test_imports.json").write_text(json.dumps(build_test_imports()))
    classes, edges = build_dialect_map()
    (OUT / "dialect_map.json").write_text(json.dumps({"classes": classes, "edges": edges}))

    n_funcs = sum(1 for v in symbols.values() for s in v if s["kind"] == "function")
    n_cls = sum(1 for v in symbols.values() for s in v if s["kind"] == "class")
    print(f"modules: {len(symbols)}, functions: {n_funcs}, classes: {n_cls}")
    print(f"dialect classes: {len(classes)}, inheritance edges: {len(edges)}")
    print(f"test files parsed: {len(json.loads((OUT / 'test_imports.json').read_text()))}")
    sizes = {f.name: f.stat().st_size for f in OUT.iterdir()}
    for k, v in sorted(sizes.items()):
        print(f"  {k}: {v} bytes")


if __name__ == "__main__":
    main()
