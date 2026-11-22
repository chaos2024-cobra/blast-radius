#!/usr/bin/env python3
"""Build the v5 keyword map: keywords from class-body string constants in ALL
sqlglot modules -> tests whose content (test-source literals + fixture files the
test's file references) contains the keyword as a token or substring (>=4 chars).
Output: work/maps/keyword_map.json  {KEYWORD: [test idx...]}
"""
import ast
import collections
import json
import re
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
MAPS = Path("/home/z/my-project/work/maps")
SAMPLE = Path("/home/z/my-project/work/blast-radius-sample/sample")

tests = json.loads((SAMPLE / "tests.json").read_text())["tests"]
test_ids = [t["id"] for t in tests]
id2idx = {t: i for i, t in enumerate(test_ids)}

# 1) fixture content
fixture_texts = {}
for p in (REPO / "tests/fixtures").rglob("*"):
    if p.suffix in (".sql", ".yml", ".yaml"):
        fixture_texts[str(p.relative_to(REPO))] = p.read_text(errors="replace")

# 2) per-test literals
test_content = {}
file_text = {}
for tf in (REPO / "tests").rglob("*.py"):
    rel = str(tf.relative_to(REPO))
    src = tf.read_text(errors="replace")
    file_text[rel] = src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            nid = f"{rel}::{cls.name}::{fn.name}"
            if nid not in id2idx:
                continue
            lits = {n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) >= 3}
            test_content[id2idx[nid]] = lits
    for fn in [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        nid = f"{rel}::{fn.name}"
        if nid in id2idx:
            lits = {n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) >= 3}
            test_content[id2idx[nid]] = lits

# 3) fixture -> test files that mention the fixture path; a test gets the fixture's content
fix_to_files = collections.defaultdict(set)   # fixture -> test file rels
for fpath in fixture_texts:
    for rel, src in file_text.items():
        if fpath in src:
            fix_to_files[fpath].add(rel)
    stem = Path(fpath).stem
    dname = Path(fpath).parent.name
    # tests/fixtures/<dirname>/<same-stem> heuristics: optimizer fixtures etc.
    for rel in file_text:
        if Path(rel).stem == dname or Path(rel).stem == stem:
            fix_to_files[fpath].add(rel)

file_tests = collections.defaultdict(set)     # test file rel -> test idx
for t in tests:
    file_tests[t["file"]].add(id2idx[t["id"]])

# 4) per-test token set + uppercase text blob (single pass)
test_tokens = {}
test_blob = {}
for idx in range(len(test_ids)):
    toks = set()
    blob = []
    for s in test_content.get(idx, ()):
        toks.update(re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", s.upper()))
        blob.append(s.upper())
    tf = tests[idx]["file"]
    for fpath, rels in fix_to_files.items():
        if tf in rels:
            blob.append(fixture_texts[fpath].upper())
            toks.update(re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", fixture_texts[fpath].upper()))
    test_tokens[idx] = toks
    test_blob[idx] = "\n".join(blob)

# 5) keywords from all module class bodies
kws = set()
for py in REPO.glob("sqlglot/**/*.py"):
    try:
        tree = ast.parse(py.read_text(errors="replace"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If)):
                    continue
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        for tok in re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", sub.value):
                            kws.add(tok.upper())

print(f"{len(kws)} keywords")

# 6) map keyword -> tests
m = {}
for kw in sorted(kws):
    hits = [idx for idx in range(len(test_ids))
            if kw in test_tokens[idx] or (len(kw) >= 4 and kw in test_blob[idx])]
    if hits:
        m[kw] = hits
sizes = sorted((len(v) for v in m.values()))
print(f"{len(m)} keywords mapped; median {sizes[len(sizes)//2]}, p90 {sizes[int(len(sizes)*0.9)]}, max {sizes[-1]}")
(MAPS / "keyword_map.json").write_text(json.dumps(m))
print("written", MAPS / "keyword_map.json")
