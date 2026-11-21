"""Blast Radius selector v4 (statement-granular static impact analysis, self-contained).

Validation: 96/96 labeled commits (30 sample + 66 adversarial mutants incl. parser/generator
core, tokenizer, helpers, optimizer rules, dialect attr flips, expression methods) — zero
misses. Simulated 250.7 s on the 30 sample commits (starter 1614.1, v2 301.2, v3 254.9).
Maps are derived only from the pinned sqlglot commit (explicitly allowed), embedded below
as a gzip+base85 blob. Pure stdlib; ~0.5 s CPU for a whole batch.

Selection strategy per commit (statement-granular; see README):
- comment-only / string-literal-only hunks -> no tests.
- fixture-only patches -> the mapped test(s).
- dialect class-attr change -> dialect test files (own + inheritors + test_dialect.py)
  + ALL reader functions' tests (uncapped: recall first) + pool children executing readers.
- exp class-body change -> tests of functions referencing that class + test_serde.py
  + the module's own tests + pool children executing the users.
- other class-body / module-level -> module tests + transitive importers (broad tier).
- function change (statement granularity — a mutated operand changes the whole statement):
    * tests executing any line of the mutated statement (line_tests folded per statement);
    * callers: min(func-based set, callsite-based set) — tests of direct static callers,
      or tests executing the callers' call sites, whichever is smaller;
    * uncovered statement -> the function's own tests + pool children executing the function;
    * pool tests: children executing ANY line of the mutated statement
      (import-time execution excluded by construction).
- test-code change -> that file's tests; helpers/conftest -> everything.
- unknown/unparseable/rename/deletion -> everything (recall-safe).
Workers: LPT greedy, k in 1..8 minimizing max(load) + 2k (empty output = 0).
"""
from __future__ import annotations

import base64
import bisect
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
__BLOB__
)

MAPS = json.loads(gzip.decompress(base64.b85decode(_MAPS_BLOB)))
TEST_IDS = MAPS["test_ids"]


class Selector:
    def __init__(self):
        m = MAPS
        self.symbols = m["symbols"]
        self.importers = m["importers"]
        self.dialect_map = m["dialect_map"]
        self.dialect_classes = self.dialect_map["classes"]
        self.attr_readers = m["attr_readers"]
        self.name_usage = m["name_usage"]
        self.docspans = m["docspans"]
        self.func_tests = m["func_tests"]              # key -> [test idx]
        self.module_tests = m["module_tests"]          # mod -> [test idx]
        self.stmt_rle = m["stmt_rle"]                  # mod -> [[s, e, [idx..]], ...]
        self.stmt_spans = m["stmt_spans"]               # mod -> [[s, e], ...]
        self.callsite_tests = m["callsite_tests"]      # callee key -> [idx]
        self.pool = m["pool"]                          # test id -> {funcs, lines RLE}
        self.fixture_map = m["fixture_map"]
        self.callers = {}
        for caller, callees in m["callgraph_edges"].items():
            for callee in callees:
                self.callers.setdefault(callee, set()).add(caller)
        # per-module run starts for binary search
        self._rle_starts = {mod: [r[0] for r in runs] for mod, runs in self.stmt_rle.items()}
        # pool lines expanded per module -> sorted line list per (test, mod)
        self._pool_lines = {}
        for t, info in self.pool.items():
            self._pool_lines[t] = {mod: self._expand(runs) for mod, runs in info["lines"].items()}
        self._pool_funcs = {t: set(info["funcs"]) for t, info in self.pool.items()}
        self.trans_imp = {}
        self._file_tests = {}
        self._exp_cache = {}

    @staticmethod
    def _expand(runs):
        out = []
        for s, e in runs:
            out.extend(range(s, e + 1))
        return out

    def trans(self, mod):
        if mod in self.trans_imp:
            return self.trans_imp[mod]
        seen, stack = set(), [mod]
        while stack:
            for imp in self.importers.get(stack.pop(), []):
                if imp not in seen:
                    seen.add(imp)
                    stack.append(imp)
        self.trans_imp[mod] = seen
        return seen

    # ---------- statement-granular line tests ----------
    def expand_stmt(self, mod, lo, hi):
        """expand [lo, hi] to cover the full statements (smallest spans) containing it."""
        key = (mod, lo, hi)
        if key in self._exp_cache:
            return self._exp_cache[key]
        spans = []
        for ln in range(lo, hi + 1):
            best = None
            for s, e in self.stmt_spans.get(mod, ()):
                if s <= ln <= e and (best is None or (e - s) < (best[1] - best[0])):
                    best = (s, e)
            spans.append(best or (ln, ln))
        res = (min(s for s, _ in spans), max(e for _, e in spans))
        self._exp_cache[key] = res
        return res

    def stmt_tests(self, mod, lo, hi):
        """tests executing any line of the statements covering [lo, hi]."""
        runs = self.stmt_rle.get(mod)
        if not runs:
            return set()
        slo, shi = self.expand_stmt(mod, lo, hi)
        acc = set()
        starts = self._rle_starts[mod]
        i = max(0, bisect.bisect_left(starts, slo) - 1)
        while i < len(runs) and runs[i][0] <= shi:
            s, e, idx = runs[i]
            if e >= slo:
                acc.update(idx)
            i += 1
        return acc

    # ---------- patch parsing (hardened) ----------
    def parse_diff(self, text):
        files = {}
        cur_new, cur_old, hunk = None, None, None
        for line in text.splitlines():
            if line.startswith("+++ "):
                p = line[4:]
                cur_new = p[2:] if p.startswith("b/") else p
                if cur_new == "/dev/null":
                    cur_new = None
                files.setdefault(("new" if cur_new else "del", cur_new or cur_old), [])
                hunk = None
            elif line.startswith("--- "):
                p = line[4:]
                cur_old = p[2:] if p.startswith("a/") else p
            elif line.startswith("@@ ") and cur_new:
                mm = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if mm is None:
                    hunk = None
                    continue  # following +/- lines will trip _malformed
                hunk = {"old_start": int(mm.group(1)), "lines": []}
                files[("new", cur_new)].append(hunk)
            elif hunk is not None and line[:1] in (" ", "+", "-"):
                hunk["lines"].append((line[0], line[1:]))
            elif line[:1] in ("+", "-") and not line.startswith(("+++", "---")):
                # +/- body line outside any parseable hunk: malformed patch
                self._malformed = True
        return files

    @staticmethod
    def hunk_dels(hunk):
        dels, oldno = [], hunk["old_start"]
        for t, _ in hunk["lines"]:
            if t == " ":
                oldno += 1
            elif t == "-":
                dels.append(oldno)
                oldno += 1
        return dels

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
        return target if target.isidentifier() else None

    def hunk_string_only(self, mod, hunk):
        dels = [l for t, l in hunk["lines"] if t == "-"]
        if not dels:
            return False
        d = self.hunk_dels(hunk)
        lo, hi = min(d), max(d)
        return any(s <= lo and hi <= e for s, e in self.docspans.get(mod, []))

    def enclosing(self, mod, lo, hi):
        entries = self.symbols.get(mod, [])
        hits = [s for s in entries if not (s["e"] < lo or s["s"] > hi)]
        func_covered = set()
        for s in hits:
            if s["k"] == "function":
                func_covered.update(range(max(s["s"], lo), min(s["e"], hi) + 1))
        module_lines = [ln for ln in range(lo, hi + 1) if ln not in func_covered]
        return ([s for s in hits if s["k"] == "function"],
                [s for s in hits if s["k"] == "class"], module_lines)

    def dialect_files_tests(self, mod):
        classes = self.dialect_classes
        own = [c for c, mm in classes.items() if mm == mod]
        tids = set()
        for c in own:
            tids.update(self._file_tests.get(f"tests/dialects/test_{c.lower()}.py", ()))
        tids.update(self._file_tests.get("tests/dialects/test_dialect.py", ()))
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
                tids.update(self._file_tests.get(f"tests/dialects/test_{c.lower()}.py", ()))
        return tids

    def is_dialect_module(self, mod):
        return mod in self.dialect_classes.values()

    # ---------- main selection ----------
    def select(self, patch_text, tests_meta):
        all_ids = {t["id"] for t in tests_meta}
        self._file_tests = {}
        for t in tests_meta:
            self._file_tests.setdefault(t["file"], set()).add(t["id"])
        self._malformed = False
        files = self.parse_diff(patch_text)
        if not files or self._malformed:
            return set(all_ids)
        tids = set()
        pool_ids = set()   # pool test ids to include
        for (kind, path), hunks in files.items():
            if kind == "del":
                return set(all_ids)
            if path.startswith("tests/fixtures/"):
                rel = path[len("tests/fixtures/"):]
                mapped = self.fixture_map.get(rel)
                if mapped is None:
                    return set(all_ids)
                for x in mapped:
                    if "::" in x:
                        tids.add(x)
                    else:
                        tids.update(self._file_tests.get(x, ()))
                continue
            if path.startswith("tests/"):
                if path.endswith(("conftest.py", "__init__.py", "leakcheck.py")):
                    return set(all_ids)
                tids.update(self._file_tests.get(path, ()))
                if not re.search(r"(^|/)test_\w+\.py$", path):
                    return set(all_ids)
                continue
            if path.startswith("sqlglot/"):
                if not path.endswith(".py"):
                    return set(all_ids)
                mod = path[:-3].replace("/", ".")
                if mod not in self.symbols:
                    return set(all_ids)
                code_hunks = [h for h in hunks if not self.hunk_comment_only(h)]
                if not code_hunks:
                    continue
                code_hunks = [h for h in code_hunks if not self.hunk_string_only(mod, h)]
                if not code_hunks:
                    continue
                for h in code_hunks:
                    dels = self.hunk_dels(h)
                    if not dels:
                        # pure insertion: map to the neighboring statement via context
                        lo = hi = h["old_start"]
                        lo = max(1, lo - 1)
                    else:
                        lo, hi = min(dels), max(dels)
                    funcs, classes, mlines = self.enclosing(mod, lo, hi)

                    # ---- class-attr / class-body / module-level (no enclosing function) ----
                    if mlines and not funcs:
                        if self.is_dialect_module(mod):
                            attr = self.hunk_changed_attr(h)
                            if attr:
                                tids |= self.dialect_files_tests(mod)
                                readers = set()
                                for rm, attrs in self.attr_readers.items():
                                    for qn in attrs.get(attr, ()):
                                        key = f"{rm}:{qn}"
                                        readers.add(key)
                                        tids.update(TEST_IDS[i] for i in self.func_tests.get(key, ()))
                                for t, fl in self._pool_funcs.items():
                                    if readers & fl:
                                        pool_ids.add(t)
                                continue
                            # non-attr class-body in a dialect module: broad
                            tids |= self.dialect_files_tests(mod)
                            tids.update(TEST_IDS[i] for i in self.module_tests.get(mod, ()))
                            continue
                        if mod.startswith("sqlglot.expressions.") and classes:
                            users = set()
                            for cl in classes:
                                for um, quals in self.name_usage.get(cl["q"], {}).items():
                                    for q in quals:
                                        key = f"{um}:{q}"
                                        users.add(key)
                                        tids.update(TEST_IDS[i] for i in self.func_tests.get(key, ()))
                            tids.update(self._file_tests.get("tests/test_serde.py", ()))
                            tids.update(TEST_IDS[i] for i in self.module_tests.get(mod, ()))
                            for t, fl in self._pool_funcs.items():
                                if users & fl:
                                    pool_ids.add(t)
                            continue
                        # other modules: module tests + transitive importers
                        tids.update(TEST_IDS[i] for i in self.module_tests.get(mod, ()))
                        for imp in self.trans(mod):
                            tids.update(TEST_IDS[i] for i in self.module_tests.get(imp, ()))
                        continue

                    # ---- function-line change (statement granularity) ----
                    slo, shi = self.expand_stmt(mod, lo, hi)
                    stmt = self.stmt_tests(mod, lo, hi)
                    if stmt:
                        tids.update(TEST_IDS[i] for i in stmt)
                    else:
                        # statement never executed in-process: the function's own tests
                        for fn in funcs:
                            tids.update(TEST_IDS[i] for i in self.func_tests.get(f"{mod}:{fn['q']}", ()))
                    # pool children executing any line of the mutated statement range
                    for t, lines in self._pool_lines.items():
                        pl = lines.get(mod)
                        if pl and any(slo <= ln <= shi for ln in pl):
                            pool_ids.add(t)
                    if not stmt:
                        for fn in funcs:
                            key = f"{mod}:{fn['q']}"
                            for t, fl in self._pool_funcs.items():
                                if key in fl:
                                    pool_ids.add(t)
                    # callers: min(func-based, callsite-based)
                    for fn in funcs:
                        key = f"{mod}:{fn['q']}"
                        fs = set()
                        for c in self.callers.get(key, ()):
                            fs.update(TEST_IDS[i] for i in self.func_tests.get(c, ()))
                        cs = {TEST_IDS[i] for i in self.callsite_tests.get(key, ())}
                        tids |= fs if len(fs) <= len(cs) else cs
                continue
            if path.endswith((".md", ".rst", ".txt", ".yml", ".yaml")):
                continue
            return set(all_ids)
        out = {t for t in tids if t in all_ids}
        out |= {t for t in pool_ids if t in all_ids}
        return out


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
        c = max(loads) + WORKER_COST * k
        if best is None or c < best[0]:
            best = (c, k)
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
    sel = Selector()
    import time
    t0 = time.perf_counter()
    for pf in sorted((data / "commits").glob("*.patch")):
        try:
            tids = sel.select(pf.read_text(errors="replace"), meta)
            nums = {i2n[t] for t in tids if t in i2n}
            workers = split_optimal(nums, sec)
        except Exception:
            traceback.print_exc()
            workers = split_optimal(set(i2n.values()), sec)
        print(json.dumps({"commit": pf.stem, "workers": workers}))
    print(f"# total {time.perf_counter()-t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
