#!/usr/bin/env python3
"""Build the final v3 submission: static-only selector with all maps embedded.

Bundles needed at runtime (all from work/maps, all derived from the pinned commit):
  ast_symbols, func_tests, module_tests, importers, dialect_map, callgraph edges,
  attr_readers, name_usage, pool_test_child_funcs (modules+funcs+module_lines),
  fixture map, docstring spans (multi-line strings), enum classes (unused, kept small),
  pool test ids, monsters (computed from tests.json at runtime instead: seconds >= 6
  and specific ids — embed the ids).
Test ids stored via a shared id table (hybrid compression).
"""
import base64
import gzip
import json
from pathlib import Path

MAPS = Path("/home/z/my-project/work/maps")
OUT = Path("/home/z/my-project/work/submission-v3/selector.py")


def build_bundle():
    load = lambda n: json.loads((MAPS / n).read_text())
    ft = load("func_tests.json")
    mt = load("module_tests.json")
    pcf = load("pool_test_child_funcs.json")
    fx = load("all_fixture_to_tests.json")

    ids = set()
    for v in ft.values():
        ids.update(v)
    for v in mt.values():
        ids.update(v)
    for v in fx.values():
        ids.update(x for x in v if "::" in x)
    ids = sorted(ids)
    idx = {t: i for i, t in enumerate(ids)}

    sym_slim = {}
    for m, entries in load("ast_symbols.json").items():
        sym_slim[m] = [{"q": s["qualname"], "k": s["kind"], "s": s["start"], "e": s["end"]}
                       for s in entries]

    # docstring spans: multi-line strings per module
    import ast as _ast
    REPO = Path("/home/z/my-project/work/sqlglot/repo")
    docspans = {}
    for py in REPO.glob("sqlglot/**/*.py"):
        mod = str(py.relative_to(REPO))[:-3].replace("/", ".")
        try:
            tree = _ast.parse(py.read_text())
        except SyntaxError:
            continue
        sl = []
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Constant) and isinstance(node.value, str)
                    and node.end_lineno > node.lineno):
                sl.append([node.lineno, node.end_lineno])
        if sl:
            docspans[mod] = sl

    tests_meta = json.loads(Path("/home/z/my-project/work/blast-radius-sample/sample/tests.json").read_text())["tests"]
    monsters = [x["id"] for x in tests_meta
                if x["seconds"] >= 6 and x["id"].endswith(("test_max_nodes", "test_generator_memory"))]

    bundle = {
        "v": 3,
        "test_ids": ids,
        "func_tests": {k: sorted({idx[i] for i in v if i in idx}) for k, v in ft.items()},
        "module_tests": {k: sorted({idx[i] for i in v if i in idx}) for k, v in mt.items()},
        "ast_symbols": sym_slim,
        "importers": load("importers.json"),
        "dialect_map": load("dialect_map.json"),
        "callgraph_edges": load("callgraph.json")["edges"],
        "attr_readers": load("attr_readers.json"),
        "name_usage": load("name_usage.json"),
        "pool_child": {t: {"modules": v["modules"], "funcs": v["funcs"],
                           "module_lines": v["module_lines"]} for t, v in pcf.items()},
        "pool_ids": sorted({idx[t] for t in pcf if t in idx}),
        "fixture_map": fx,
        "docspans": docspans,
        "monsters": monsters,
    }
    return bundle


TEMPLATE = open(Path("/home/z/my-project/scripts/selector_v3_template.py")).read()


def main():
    bundle = build_bundle()
    raw = json.dumps(bundle, separators=(",", ":")).encode()
    blob = base64.b85encode(gzip.compress(raw, 9)).decode()
    lines = [blob[i:i + 96] for i in range(0, len(blob), 96)]
    lit = "\n".join('    "%s"' % l for l in lines)
    src = TEMPLATE.replace("%BLOB%", lit)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(src)
    import ast
    ast.parse(src)
    print(f"wrote {OUT}: {len(src)} bytes ({len(raw)/1e6:.1f}M raw -> blob {len(blob)/1e6:.2f}M), syntax ok")


if __name__ == "__main__":
    main()
