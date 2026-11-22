#!/usr/bin/env python3
"""Build the v4 submission: compact maps + final selector logic -> selector.py blob.

Compaction strategy (164MB of raw maps -> a few MB):
- line_tests (per-line test ids) folded to STATEMENT granularity with run-length
  encoding: [start, end, [test indices]] per module.
- callsites + line_tests merged into callsite_tests: per callee, the union of tests
  executing any call-site statement (the hybrid caller rule needs min(func, site)).
- func_tests / module_tests store test INDICES (ints) not ids.
- pool_child: funcs kept, module_lines run-length encoded.
Everything gzip + base85 embedded in selector.py (pure stdlib runtime).
"""
import base64
import gzip
import json
from pathlib import Path

MAPS = Path("/home/z/my-project/work/maps")
OUT = Path("/home/z/my-project/work/submission-v4")
OUT.mkdir(exist_ok=True)

load = lambda n: json.loads((MAPS / n).read_text())

tests_meta = json.loads(Path("/home/z/my-project/work/blast-radius-sample/sample/tests.json").read_text())["tests"]
test_ids = [t["id"] for t in tests_meta]
id2idx = {t: i for i, t in enumerate(test_ids)}

line_tests = load("line_tests.json")
func_tests = load("func_tests.json")
module_tests = load("module_tests.json")
symbols = load("ast_symbols.json")
importers = load("importers.json")
dialect_map = load("dialect_map.json")
attr_readers = load("attr_readers.json")
name_usage = load("name_usage.json")
fixture_map = load("all_fixture_to_tests.json")
pool_child = load("pool_test_child_funcs.json")
callsites = load("callsites.json")
stmt_spans = load("stmt_spans.json")

# docspans from v3 blob (module -> [[s,e]] of string-literal spans); rebuild from tree
import ast
REPO = Path("/home/z/my-project/work/sqlglot/repo")
docspans = {}
for py in REPO.glob("sqlglot/**/*.py"):
    mod = str(py.relative_to(REPO))[:-3].replace("/", ".")
    try:
        tree = ast.parse(py.read_text())
    except SyntaxError:
        continue
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "\n" in node.value:
            spans.append([node.lineno, node.end_lineno])
    if spans:
        docspans[mod] = spans

# ---- stmt-granular line tests, run-length encoded ----
def smallest_span(spans, ln):
    best = None
    for s, e in spans:
        if s <= ln <= e and (best is None or (e - s) < (best[1] - best[0])):
            best = (s, e)
    return best

stmt_lines_map = {}   # mod -> {line: stmt_id(s,e)} resolved per line
for mod, spans in stmt_spans.items():
    m = {}
    for s, e in spans:
        for ln in range(s, e + 1):
            cur = m.get(ln)
            if cur is None or (e - s) < (cur[1] - cur[0]):
                m[ln] = (s, e)
    stmt_lines_map[mod] = m

stmt_tests = {}       # (mod, s, e) -> set(idx)
def stmt_test_idx(mod, ln):
    st = stmt_lines_map.get(mod, {}).get(ln)
    key = (mod, st) if st else (mod, (ln, ln))
    if key in stmt_tests:
        return key, stmt_tests[key]
    acc = set()
    lo, hi = key[1]
    for l2 in range(lo, hi + 1):
        for tid in line_tests.get(f"{mod}:{l2}", ()):
            if tid in id2idx:
                acc.add(id2idx[tid])
    stmt_tests[key] = acc
    return key, acc

rle = {}              # mod -> sorted [[start, end, [idx...]], ...]
for mod, m in stmt_lines_map.items():
    by_stmt = {}
    for ln, st in m.items():
        by_stmt.setdefault(st, set()).update(stmt_test_idx(mod, ln)[1])
    runs = sorted([[s, e, sorted(ix)] for (s, e), ix in by_stmt.items()])
    rle[mod] = runs

# ---- callsite tests (per callee, union of call-site statement tests) ----
callsite_tests = {}
for callee, callers in callsites.items():
    acc = set()
    for caller, spans in callers.items():
        cmod = caller.split(":")[0]
        for s, e in spans:
            for ln in range(s, e + 1):
                _, ix = stmt_test_idx(cmod, ln)
                acc |= ix
    if acc:
        callsite_tests[callee] = sorted(acc)

# ---- compact func/module tests ----
ft_idx = {k: sorted({id2idx[t] for t in v if t in id2idx}) for k, v in func_tests.items()}
ft_idx = {k: v for k, v in ft_idx.items() if v}
mt_idx = {k: sorted({id2idx[t] for t in v if t in id2idx}) for k, v in module_tests.items()}
mt_idx = {k: v for k, v in mt_idx.items() if v}

# ---- pool children compact ----
pool = {}
for t, info in pool_child.items():
    if t not in id2idx:
        continue
    lines = {}
    for mod, lns in info.get("module_lines", {}).items():
        lns = sorted(set(lns))
        runs = []
        for ln in lns:
            if runs and ln == runs[-1][1] + 1:
                runs[-1][1] = ln
            else:
                runs.append([ln, ln])
        lines[mod] = runs
    pool[t] = {"funcs": info.get("funcs", []), "lines": lines}

BLOB = {
    "test_ids": test_ids,
    "symbols": {m: [{"k": s["kind"], "s": s["start"], "e": s["end"], "q": s["qualname"]}
                    for s in v] for m, v in symbols.items()},
    "importers": importers,
    "dialect_map": dialect_map,
    "attr_readers": attr_readers,
    "name_usage": name_usage,
    "docspans": docspans,
    "func_tests": ft_idx,
    "module_tests": mt_idx,
    "stmt_rle": rle,
    "stmt_spans": {m: [list(x) for x in v] for m, v in stmt_spans.items()},
    "callsite_tests": callsite_tests,
    "callgraph_edges": load("callgraph.json")["edges"],
    "pool": pool,
    "fixture_map": fixture_map,
}
raw = json.dumps(BLOB, separators=(",", ":")).encode()
blob = base64.b85encode(gzip.compress(raw, 9)).decode()
print(f"blob size: {len(blob)/1e6:.1f} MB (raw {len(raw)/1e6:.1f} MB)")

# chunk the blob into source lines
lines = [blob[i:i+120] for i in range(0, len(blob), 120)]
with open(OUT / "_blob_part.txt", "w") as f:
    f.write("\n".join(f'    "{l}"' for l in lines))
print("blob part written; selector template next")
