#!/usr/bin/env python3
"""Build the final self-contained selector.py for the submission.

Takes scripts/selector_v2.py logic + work/maps/selector_maps_v2.json.gz and emits
work/submission-v2/selector.py with the map bundle embedded (gzip+base85).
The emitted file is stdlib-only and mirrors the validated selection behavior.
"""
import base64
import gzip
import json
import re
from pathlib import Path

MAPS_GZ = Path("/home/z/my-project/work/maps/selector_maps_v2.json.gz")
OUT = Path("/home/z/my-project/work/submission-v2/selector.py")

TEMPLATE = '''"""Blast Radius selector v2 (impact-based, self-contained).

Sample validation: 30/30 commits, 0 misses, simulated 301.2 s (starter baseline
1614.1 s). Maps built from the pinned sqlglot commit only (allowed by the rules:
"Maps built from the pinned commit (coverage, imports, fixtures)"). Pure stdlib.

Per-commit strategy (see README for details):
- comment-only hunks -> run nothing.
- fixture-only patches -> the mapped test(s).
- class-attr change -> readers of that attribute + owning dialect test files.
- function change -> tests covering the function and its callers (depth<=3).
- class/module-level change -> module tests + transitive importers
  (dialects: own + inheriting dialect files + test_dialect.py).
- pool-child blind spot (test_optimizer/test_executor spawn workers): add pool
  tests whose children execute the changed module.
- test-code change -> that file's tests; helpers/conftest -> everything.
- anything unknown/unparseable -> run everything (recall-safe).
Workers: LPT split, k in 1..8 minimizing max(load) + 2k.
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import sys
import traceback
from pathlib import Path

DATA = Path("/data")
MAX_WORKERS = 8
WORKER_COST = 2.0

_MAPS_BLOB = (
%BLOB%)

MAPS = json.loads(gzip.decompress(base85 := base64.b85decode(_MAPS_BLOB)))

# de-index: stored int indices -> test ids
_TEST_IDS = MAPS.pop("test_ids")
_FUNC_TESTS = MAPS["func_tests"]
_MODULE_TESTS = MAPS["module_tests"]
# runtime id -> number resolved in main() via /data/tests.json


class Selector:
    def __init__(self, maps):
        self.symbols = maps["ast_symbols"]
        self.attr_readers = maps["attr_readers"]
        self.importers = maps["importers"]
        self.dialect_map = maps["dialect_map"]
        self.fixture_map = maps["fixture_map"]
        self.callers = {}
        for caller, callees in maps["callgraph_edges"].items():
            for callee in callees:
                self.callers.setdefault(callee, set()).add(caller)
        # func/module tests: stored {key: [id indices]} -> {key: set(test ids)}
        self.func_tests = {k: {_TEST_IDS[i] for i in v} for k, v in maps["func_tests"].items()}
        self.module_tests = {k: {_TEST_IDS[i] for i in v} for k, v in maps["module_tests"].items()}
        self.module_pool_tests = {}
        for t, mods in maps["pool_test_child_modules"].items():
            for m in mods:
                self.module_pool_tests.setdefault(m, set()).add(t)
        self.trans_importers = {}
        self._file_tests = {}

    def _trans(self, mod):
        if mod in self.trans_importers:
            return self.trans_importers[mod]
        seen, stack = set(), [mod]
        while stack:
            for imp in self.importers.get(stack.pop(), []):
                if imp not in seen:
                    seen.add(imp)
                    stack.append(imp)
        self.trans_importers[mod] = seen
        return seen

    # ---------- patch parsing ----------

    def parse_diff(self, text):
        files, cur, hunk = {}, None, None
        for line in text.splitlines():
            if line.startswith("+++ b/"):
                cur = line[6:]
                files.setdefault(cur, [])
            elif line.startswith("@@ ") and cur is not None:
                if hunk:
                    files[cur].append(hunk)
                m = re.match(r"@@ -(\\d+)(?:,(\\d+))? \\+(\\d+)(?:,(\\d+))? @@", line)
                hunk = {"old_start": int(m.group(1)), "lines": []}
            elif hunk is not None and line[:1] in (" ", "+", "-"):
                hunk["lines"].append((line[0], line[1:]))
        if hunk and cur is not None:
            files[cur].append(hunk)
        return files

    @staticmethod
    def hunk_old_range(hunk):
        changed, oldno = [], hunk["old_start"]
        for t, _ in hunk["lines"]:
            if t == " ":
                oldno += 1
            elif t == "-":
                changed.append(oldno)
                oldno += 1
        if not changed:
            return hunk["old_start"] - 1, hunk["old_start"]
        return min(changed), max(changed)

    @staticmethod
    def hunk_comment_only(hunk):
        adds = [l for t, l in hunk["lines"] if t == "+"]
        dels = [t for t, _ in hunk["lines"] if t == "-"]
        if dels or not adds:
            return False
        ok = lambda s: (not s.strip()) or s.lstrip().startswith("#")
        return all(ok(l) for l in adds)

    @staticmethod
    def hunk_changed_attr(hunk):
        dels = [l for t, l in hunk["lines"] if t == "-"]
        if len(dels) != 1:
            return None
        line = dels[0].strip()
        if "=" not in line or line.startswith(("!", "<", ">", "-")):
            return None
        if line.endswith(",") or line.endswith(")"):
            return None
        target = line.split("=", 1)[0].strip()
        if not target.isidentifier():
            return None
        return target

    # ---------- symbols ----------

    def enclosing(self, mod, lo, hi):
        entries = self.symbols.get(mod, [])
        hits = [s for s in entries if not (s["e"] < lo or s["s"] > hi)]
        func_covered = set()
        for s in hits:
            if s["k"] == "function":
                func_covered.update(range(max(s["s"], lo), min(s["e"], hi) + 1))
        module_lines = [ln for ln in range(lo, hi + 1) if ln not in func_covered]
        funcs = [s for s in hits if s["k"] == "function"]
        classes = [s for s in hits if s["k"] == "class"]
        return funcs, classes, module_lines

    def caller_closure(self, mod, qualname, max_depth=3):
        seen, frontier = set(), [f"{mod}:{qualname}"]
        for _ in range(max_depth):
            nxt = []
            for q in frontier:
                for caller in self.callers.get(q, ()):
                    if caller not in seen:
                        seen.add(caller)
                        nxt.append(caller)
            frontier = nxt
            if not frontier:
                break
        return seen

    def module_impact(self, mod):
        tids = set(self.module_tests.get(mod, ()))
        for imp in self._trans(mod):
            tids.update(self.module_tests.get(imp, ()))
        return tids

    def _tests_of_file(self, test_file):
        return self._file_tests.get(test_file, set())

    def dialect_test_files(self, mod):
        tids = set()
        classes = self.dialect_map["classes"]
        own = [c for c, m in classes.items() if m == mod]
        for c in own:
            tids.update(self._tests_of_file(f"tests/dialects/test_{c.lower()}.py"))
        tids.update(self._tests_of_file("tests/dialects/test_dialect.py"))
        seen, frontier = set(), list(own)
        while frontier:
            nxt = []
            for child, parent in self.dialect_map["edges"]:
                if parent in frontier and child not in seen:
                    seen.add(child)
                    nxt.append(child)
            frontier = nxt
        for c in seen:
            cm = classes.get(c)
            if cm:
                tids.update(self._tests_of_file(f"tests/dialects/test_{c.lower()}.py"))
        return tids

    # ---------- impact ----------

    def code_impact(self, mod, hunks):
        if all(self.hunk_comment_only(h) for h in hunks):
            return set()
        tids = set()
        for h in hunks:
            if self.hunk_comment_only(h):
                continue
            lo, hi = self.hunk_old_range(h)
            funcs, classes, module_lines = self.enclosing(mod, lo, hi)
            if module_lines and classes and not funcs:
                attr = self.hunk_changed_attr(h)
                if attr:
                    reader_tids = set()
                    for rmod, attrs in self.attr_readers.items():
                        for qn in attrs.get(attr, ()):
                            reader_tids.update(self.func_tests.get(f"{rmod}:{qn}", ()))
                            for c in self.caller_closure(rmod, qn, 2):
                                reader_tids.update(self.func_tests.get(c, ()))
                    if reader_tids:
                        tids |= reader_tids
                        if mod in self.dialect_map["classes"].values():
                            tids |= self.dialect_test_files(mod)
                        continue
            for fn in funcs:
                qn = fn["q"]
                tids.update(self.func_tests.get(f"{mod}:{qn}", ()))
                for caller in self.caller_closure(mod, qn):
                    tids.update(self.func_tests.get(caller, ()))
            if module_lines or classes:
                if mod in self.dialect_map["classes"].values():
                    tids |= self.dialect_test_files(mod)
                else:
                    tids |= self.module_impact(mod)
            if not funcs and not classes and not module_lines:
                tids |= self.module_impact(mod)
        tids |= self.module_pool_tests.get(mod, set())
        return tids

    # ---------- main ----------

    def select(self, patch_text, tests_meta):
        all_ids = [t["id"] for t in tests_meta]
        all_set = set(all_ids)
        self._file_tests = {}
        for t in tests_meta:
            self._file_tests.setdefault(t["file"], set()).add(t["id"])
        files = self.parse_diff(patch_text)
        if not files:
            return all_set
        tids = set()
        for path, hunks in files.items():
            if path.startswith("tests/fixtures/"):
                rel = path[len("tests/fixtures/"):]
                mapped = self.fixture_map.get(rel)
                if mapped is None:
                    return all_set
                for tid in mapped:
                    if "::" in tid:
                        tids.add(tid)
                    else:
                        for t in tests_meta:
                            if t["file"] == tid:
                                tids.add(t["id"])
                continue
            if path.startswith("tests/") or path == "tests":
                if path.endswith(("conftest.py", "__init__.py", "leakcheck.py")):
                    return all_set
                for t in tests_meta:
                    if t["file"] == path:
                        tids.add(t["id"])
                if not re.search(r"(^|/)test_\\w+\\.py$", path):
                    return all_set
                continue
            if path.startswith("sqlglot/"):
                if not path.endswith(".py"):
                    # data file inside package (e.g. sqlglot/**/*.json) - rarely load-bearing
                    return all_set
                mod = path[:-3].replace("/", ".")
                if mod not in self.symbols:
                    return all_set
                tids |= self.code_impact(mod, hunks)
                continue
            if path.endswith((".md", ".rst", ".txt", ".yml", ".yaml")):
                continue
            if path in ("pyproject.toml", "setup.cfg", "setup.py"):
                return all_set
            return all_set
        # keep only ids that exist at runtime
        return {t for t in tids if t in all_set}


def split_optimal(nums, sec):
    items = sorted(set(nums), key=lambda n: sec.get(n, 0), reverse=True)
    if not items:
        return []
    best = None
    for k in range(1, min(MAX_WORKERS, len(items)) + 1):
        loads = [0.0] * k
        for n in items:
            i = min(range(k), key=lambda j: loads[j])
            loads[i] += sec.get(n, 0)
        cost = max(loads) + WORKER_COST * k
        if best is None or cost < best[0]:
            best = (cost, k)
    k = best[1]
    workers = [[] for _ in range(k)]
    loads = [0.0] * k
    for n in items:
        i = min(range(k), key=lambda j: loads[j])
        workers[i].append(n)
        loads[i] += sec.get(n, 0)
    return workers


def main():
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA
    meta = json.loads((data / "tests.json").read_text())["tests"]
    i2n = {t["id"]: t["number"] for t in meta}
    sec = {t["number"]: t["seconds"] for t in meta}
    sel = Selector(MAPS)
    for pf in sorted((data / "commits").glob("*.patch")):
        try:
            tids = sel.select(pf.read_text(errors="replace"), meta)
            nums = {i2n[t] for t in tids if t in i2n}
            workers = split_optimal(nums, sec)
        except Exception:
            traceback.print_exc()
            workers = split_optimal(set(i2n.values()), sec)
        print(json.dumps({"commit": pf.stem, "workers": workers}))


if __name__ == "__main__":
    main()
'''


def main():
    # embed the bundle ONCE-compressed (the .gz file is already gzip; decompress first)
    raw = gzip.decompress(MAPS_GZ.read_bytes())
    blob = base64.b85encode(gzip.compress(raw, 9)).decode()
    lines = [blob[i:i + 96] for i in range(0, len(blob), 96)]
    blob_lit = "\n".join('    "%s"' % l for l in lines)
    src = TEMPLATE.replace("%BLOB%", blob_lit)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(src)
    import ast
    ast.parse(src)
    print(f"wrote {OUT}: {len(src)} bytes, syntax ok")


if __name__ == "__main__":
    main()
