#!/usr/bin/env python3
"""Build call-site map v2 with a GLOBAL method-name registry.

Resolution rules for a Call node:
- Name f: same-module top-level function with that name.
- Attribute f.attr: every method (of any class, any module) named f.attr, PLUS
  same-module functions named f.attr. Over-approximates edges for overloaded names;
  recall-safe.
Edges: callee_key -> {caller_key: [[stmt_start, stmt_end], ...]}
"""
import ast
import json
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
OUT = Path("/home/z/my-project/work/maps/callsites.json")

# pass 1: global registries
global_methods = {}   # method name -> [full qual "mod:Class.method"]
global_funcs = {}     # func name -> [full qual "mod:func"]
mod_symbols = {}      # mod -> {"funcs": {name: qual}, "methods": {name: [qual]}}

for py in sorted(REPO.glob("sqlglot/**/*.py")):
    mod = str(py.relative_to(REPO))[:-3].replace("/", ".")
    try:
        tree = ast.parse(py.read_text())
    except SyntaxError:
        continue

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{ch.name}" if prefix else ch.name
                if isinstance(ch, ast.ClassDef):
                    walk(ch, name)
                else:
                    full = f"{mod}:{name}"
                    if "." in name:  # method
                        mname = name.rsplit(".", 1)[-1]
                        global_methods.setdefault(mname, []).append(full)
                        mod_symbols.setdefault(mod, {"funcs": {}, "methods": {}})["methods"].setdefault(mname, []).append(full)
                    else:
                        global_funcs.setdefault(name, []).append(full)
                        mod_symbols.setdefault(mod, {"funcs": {}, "methods": {}})["funcs"][name] = full
            else:
                walk(ch, prefix)

    walk(tree, "")

callsites = {}
for py in sorted(REPO.glob("sqlglot/**/*.py")):
    mod = str(py.relative_to(REPO))[:-3].replace("/", ".")
    try:
        tree = ast.parse(py.read_text())
    except SyntaxError:
        continue
    qn = {}

    def walk2(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{ch.name}" if prefix else ch.name
                qn[ch] = name
                if isinstance(ch, ast.ClassDef):
                    walk2(ch, name)
                else:
                    walk2(ch, name)
            else:
                walk2(ch, prefix)

    walk2(tree, "")

    func_nodes = [(n, name) for n, name in qn.items()
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    stmts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            try:
                stmts.append((node.lineno, node.end_lineno))
            except AttributeError:
                pass
        elif isinstance(node, (ast.BoolOp, ast.IfExp)):
            try:
                stmts.append((node.lineno, node.end_lineno))
            except AttributeError:
                pass
    stmts.sort(key=lambda s: s[1] - s[0])

    def enc_func(n):
        best = None
        for f, name in func_nodes:
            if f.lineno <= n.lineno <= (f.end_lineno or f.lineno):
                if best is None or (f.end_lineno - f.lineno) < (best[1].end_lineno - best[1].lineno):
                    best = (name, f)
        return best[0] if best else None

    def stmt_of(n):
        for s, e in stmts:
            if s <= n.lineno <= e:
                return (s, e)
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        callees = []
        if isinstance(f, ast.Name):
            callees = global_funcs.get(f.id, [])
        elif isinstance(f, ast.Attribute):
            callees = global_methods.get(f.attr, []) + global_funcs.get(f.attr, [])
        if not callees:
            continue
        caller = enc_func(node)
        if not caller:
            continue
        st = stmt_of(node)
        if not st:
            continue
        ckey = f"{mod}:{caller}"
        for callee in callees:
            callsites.setdefault(callee, {}).setdefault(ckey, []).append([st[0], st[1]])

OUT.write_text(json.dumps(callsites))
print(f"callees: {len(callsites)}, edges: {sum(len(v) for v in callsites.values())}")
