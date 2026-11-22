#!/usr/bin/env python3
"""Build the static call graph of the sqlglot package at the pinned commit.

Outputs work/maps/callgraph.json:
  {"edges": {caller_qual: [callee_qual, ...]}, "calls_by_file": {mod: {line: [callee_qual]}}}

Resolution of call targets (static, best effort):
  - ast.Name call: local/module symbol (function or class defined in module,
    or imported name re-resolved through imports.json)
  - ast.Attribute call: self.method -> resolve in same class; module.attr ->
    resolve in that module; else unresolved (drop)
  - built-in/stdlib/dynamic calls: dropped (conservative direction is handled
    by the selector's fallbacks, not by inflating the call graph)
"""
import ast
import json
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
OUT = Path("/home/z/my-project/work/maps")


def parse(py: Path):
    try:
        return ast.parse(py.read_text())
    except SyntaxError:
        return None


def module_of(py: Path) -> str:
    return str(py.relative_to(REPO).with_suffix("")).replace("/", ".")


def build():
    # 1. module symbol tables: name -> qualname for functions/classes (incl. methods)
    tables = {}  # mod -> {name: [qualnames]}
    for py in sorted(REPO.glob("sqlglot/**/*.py")):
        mod = module_of(py)
        tree = parse(py)
        if tree is None:
            continue
        names = {}

        def walk(node, prefix):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    qn = ".".join(prefix + [child.name])
                    names.setdefault(child.name, []).append(qn)
                    walk(child, prefix + [child.name])
                else:
                    walk(child, prefix)

        walk(tree, [])
        tables[mod] = names

    # 2. import alias map: mod -> {local_name: (source_module, source_name)}
    impmap = {}
    for py in sorted(REPO.glob("sqlglot/**/*.py")):
        mod = module_of(py)
        tree = parse(py)
        if tree is None:
            continue
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    aliases[a.asname or a.name] = (node.module, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    top = a.name.split(".")[0]
                    if a.name.startswith("sqlglot"):
                        aliases[a.asname or top] = (a.name, "*")
        impmap[mod] = aliases

    edges = {}       # caller qual (mod:qual) -> set of callee quals (mod:qual)
    calls_by_file = {}  # mod -> {line: [callee qual]}

    def qual_of(mod, name_node, class_ctx):
        """Best-effort resolve a name to (mod, qualname) or None."""
        if isinstance(name_node, ast.Name):
            name = name_node.id
            # local function/class in this module?
            if name in tables.get(mod, {}):
                # prefer one in the current class context if ambiguous
                cands = tables[mod][name]
                if class_ctx:
                    pref = [c for c in cands if c.startswith(class_ctx + ".")]
                    if pref:
                        return mod, pref[0]
                return mod, cands[0]
            # imported?
            if name in impmap.get(mod, {}):
                src_mod, src_name = impmap[mod][name]
                if src_mod in tables:
                    if src_name == "*":
                        return None
                    if src_name in tables[src_mod]:
                        return src_mod, tables[src_mod][src_name][0]
            return None
        if isinstance(name_node, ast.Attribute):
            base = name_node.value
            attr = name_node.attr
            # self.method / cls.method
            if isinstance(base, ast.Name) and base.id in ("self", "cls") and class_ctx:
                cands = tables.get(mod, {}).get(attr, [])
                pref = [c for c in cands if c.startswith(class_ctx + ".")]
                if pref:
                    return mod, pref[0]
                if cands:
                    return mod, cands[0]
            # module.attr where module was imported
            if isinstance(base, ast.Name):
                b = base.id
                if b in impmap.get(mod, {}):
                    src_mod, _ = impmap[mod][b]
                    if src_mod in tables and attr in tables[src_mod]:
                        return src_mod, tables[src_mod][attr][0]
                # same-module attribute access (rare) e.g. Foo.bar
                if b in tables.get(mod, {}) and attr in tables.get(mod, {}):
                    return None
            return None
        return None

    for py in sorted(REPO.glob("sqlglot/**/*.py")):
        mod = module_of(py)
        tree = parse(py)
        if tree is None:
            continue

        def walk(node, class_stack, func_stack):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(child, class_stack + [child.name], func_stack)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qn = ".".join(class_stack + [child.name])
                    caller = f"{mod}:{qn}"
                    for sub in ast.walk(child):
                        if isinstance(sub, ast.Call):
                            tgt = qual_of(mod, sub.func, ".".join(class_stack))
                            if tgt:
                                edges.setdefault(caller, set()).add(f"{tgt[0]}:{tgt[1]}")
                                calls_by_file.setdefault(mod, {}).setdefault(sub.lineno, set()).add(f"{tgt[0]}:{tgt[1]}")
                    walk(child, class_stack, func_stack + [child.name])
                else:
                    walk(child, class_stack, func_stack)

        walk(tree, [], [])

    payload = {
        "edges": {k: sorted(v) for k, v in edges.items()},
        "calls_by_file": {m: {str(ln): sorted(v) for ln, v in d.items()} for m, d in calls_by_file.items()},
    }
    (OUT / "callgraph.json").write_text(json.dumps(payload))
    n_edges = sum(len(v) for v in edges.values())
    print(f"caller functions: {len(edges)}, call edges: {n_edges}")
    print(f"size: {(OUT / 'callgraph.json').stat().st_size} bytes")


if __name__ == "__main__":
    build()
