#!/usr/bin/env python3
"""Stage 3: rewire V6Engine + Selector onto the v9 shared layer (fixes 1-6)."""
import ast
from pathlib import Path

WORK = Path("/home/z/my-project/work")
src = (WORK / "submission-v9/selector_v9_stage2.py").read_text()

# ------------------------------------------------------------- V6Engine rewiring
v6_parse = '''    def parse_diff(self, text):
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
                mm = re.match(r"@@ -(\\d+)(?:,(\\d+))? \\+(\\d+)(?:,(\\d+))? @@", line)
                if mm is None:
                    hunk = None
                    continue
                hunk = {"old_start": int(mm.group(1)), "lines": []}
                files[("new", cur_new)].append(hunk)
            elif hunk is not None and line[:1] in (" ", "+", "-"):
                hunk["lines"].append((line[0], line[1:]))
            elif line[:1] in ("+", "-") and not line.startswith(("+++", "---")):
                self._malformed = True
        return files
'''
v6_parse_new = '''    def parse_diff(self, text):
        files, run_all = parse_diff9(text)
        if run_all:
            self._malformed = True
        return files
'''
assert src.count(v6_parse) == 1, "v6 parse_diff not found"
src = src.replace(v6_parse, v6_parse_new)

# V6 hunk_dels: keep (used for del range) but the lo/hi computation in select
# must include add-run anchors -> replace the block in select.
v6_lohi_old = '''                for h in code_hunks:
                    dels = self.hunk_dels(h)
                    if not dels:
                        lo = hi = h["old_start"]
                        lo = max(1, lo - 1)
                    else:
                        lo, hi = min(dels), max(dels)
'''
v6_lohi_new = '''                for h in hunks_for_scope:
                    dels = self.hunk_dels(h)
                    ranges = hunk_ranges9(h)
                    lo = min(r[0] for r in ranges)
                    hi = max(r[1] for r in ranges)
                    lo = max(1, lo)
'''
assert src.count(v6_lohi_old) == 1, "v6 lo/hi block not found"
src = src.replace(v6_lohi_old, v6_lohi_new)

# V6 comment_only/string_only -> shared
v6_co = '''    @staticmethod
    def hunk_comment_only(hunk):
        adds = [l for t, l in hunk["lines"] if t == "+"]
        dels = [t for t, _ in hunk["lines"] if t == "-"]
        if dels or not adds:
            return False
        ok = lambda s: (not s.strip()) or s.lstrip().startswith("#")
        return all(ok(l) for l in adds)
'''
# already replaced in stage 2 (both copies); check
assert src.count(v6_co) == 0, "v6 comment_only still present"

v6_so = '''    def hunk_string_only(self, mod, hunk):
        dels = [l for t, l in hunk["lines"] if t == "-"]
        if not dels:
            return False
        d = self.hunk_dels(hunk)
        lo, hi = min(d), max(d)
        return any(s <= lo and hi <= e for s, e in self.docspans.get(mod, []))
'''
v6_so_new = '''    def hunk_string_only(self, mod, hunk):
        return hunk_string_only9(mod, hunk)
'''
assert src.count(v6_so) == 1, "v6 hunk_string_only not found"
src = src.replace(v6_so, v6_so_new)

# V6 select: comment-only handling (fix 1)
v6_sel_old = '''                code_hunks = [h for h in hunks if not self.hunk_comment_only(h)]
                if not code_hunks:
                    continue
                code_hunks = [h for h in code_hunks if not self.hunk_string_only(mod, h)]
                if not code_hunks:
                    continue
'''
v6_sel_new = '''                code_hunks = [h for h in hunks if not self.hunk_comment_only(h)]
                comment_plain = [h for h in hunks
                                 if self.hunk_comment_only(h) and not comment_hunk_live9(mod, h)]
                live_str_hunks = [h for h in hunks
                                  if self.hunk_comment_only(h) and comment_hunk_live9(mod, h)]
                if not code_hunks and not comment_plain and not live_str_hunks:
                    continue
                code_hunks = [h for h in code_hunks if not self.hunk_string_only(mod, h)]
                hunks_for_scope = code_hunks + live_str_hunks
                if not hunks_for_scope and not comment_plain:
                    continue
                if comment_plain:
                    # fix 1: comment-only outside strings still selects the
                    # module floor (<= 60 tests) or the enclosing scope
                    mt = self.module_tests.get(mod, ())
                    if len(mt) <= 60:
                        pool_ids.update(mt)
                        tids.update(TEST_IDS6[i] for i in mt)
                    else:
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.callers.get(f"{mod}:{fn['q']}", ()):
                                    tids.update(TEST_IDS6[i] for i in self.func_tests.get(c, ()))
                            if mlines or classes:
                                tids.update(TEST_IDS6[i] for i in mt)
'''
assert src.count(v6_sel_old) == 1, "v6 select head not found"
src = src.replace(v6_sel_old, v6_sel_new)

# V6 pool loop uses code_hunks after filtering; check what it references now
v6_pool = '''                    for t, fl in self._pool_funcs.items():
                        if key in fl:
                            pool_ids.add(t)
'''
# (that block is inside the function-line change section; it iterates funcs,
# not code_hunks - fine)

# ---------------------------------------------------------------- Selector class
sel_old = '''    def select(self, patch_text, tests_meta):
        sel = self.v3.select(patch_text, tests_meta) | self.v6.select(patch_text, tests_meta)
        files = self.v6.parse_diff(patch_text)
        if not files:
            return set(t["id"] for t in tests_meta)
        for (kind, path), hunks in files.items():
            if not path.startswith("sqlglot/") or not path.endswith(".py"):
                continue
            mod = path[:-3].replace("/", ".")
            live = [h for h in hunks
                    if not self.v6.hunk_comment_only(h)
                    and not (mod in MAPS6["docspans"] and self.v6.hunk_string_only(mod, h))]
            if not live:
                continue
            mt = self._mod_tests.get(mod, set())
            if len(mt) <= self.MODULE_FLOOR_MAX:
                sel |= mt
        return sel
'''
sel_new = '''    def select(self, patch_text, tests_meta):
        sel = self.v3.select(patch_text, tests_meta) | self.v6.select(patch_text, tests_meta)
        files, run_all = parse_diff9(patch_text)
        all_ids = set(t["id"] for t in tests_meta)
        if run_all or not files:
            return all_ids
        # per-file map for the closure/read floors
        file_tests = {}
        for t in tests_meta:
            file_tests.setdefault(t["file"], set()).add(t["id"])
        changed_paths = [path for (_kind, path) in files.keys()]
        for (kind, path), hunks in files.items():
            if kind == "del" or path is None:
                return all_ids
            # fix 6: rename/mode/binary of tracked files -> run-all (parse_diff9
            # flags it, but double-check paths not under the known roots)
            if not path.startswith(("sqlglot/", "sqlglotc/", "tests/", "docs/")) and \\
                    not path.endswith((".md", ".rst", ".txt", ".yml", ".yaml", ".toml",
                                      ".cfg", ".ini", ".json", ".lock", ".in", ".gitignore")):
                return all_ids
            if path.startswith("sqlglotc/"):
                # fix 5: any change under sqlglotc/ selects the reader tests
                sel |= self._read_tests(path)
            if path.startswith("sqlglot/") and path.endswith(".py"):
                mod = path[:-3].replace("/", ".")
                live = [h for h in hunks
                        if not self.v6.hunk_comment_only(h)
                        and not (mod in MAPS6["docspans"] and self.v6.hunk_string_only(mod, h))]
                live = [h for h in live if not comment_hunk_live9(mod, h) or True]
                if live:
                    # fix 5: source-reading tests
                    sel |= self._read_tests(path)
                    # module floor (v8 behavior)
                    mt = self._mod_tests.get(mod, set())
                    if len(mt) <= self.MODULE_FLOOR_MAX:
                        sel |= mt
                # fix 5 for typing: those files are read as TEXT, so even a
                # comment/docstring-only change alters what the reader sees
                if path.startswith("sqlglot/typing/"):
                    sel |= self._read_tests(path)
            if path.startswith("tests/") and path.endswith(".py"):
                # fix 4: editing a test file selects its transitive importers
                for importer in TEST_CLOSURE.get(path, ()):
                    sel |= file_tests.get(importer, set())
                # a non-test helper file under tests/ (e.g. helpers.py) also
                # selects its importers; test files themselves handled above
                if not re.search(r"(^|/)test_\\w+\\.py$", path) and path not in (
                        "tests/conftest.py", "tests/__init__.py", "tests/leakcheck.py",
                        "tests/dialects/__init__.py"):
                    for importer in TEST_CLOSURE.get(path, ()):
                        sel |= file_tests.get(importer, set())
        return sel

    def _read_tests(self, path):
        return set(READ_MAP.get(path, ()))
'''
assert src.count(sel_old) == 1, "Selector.select not found"
src = src.replace(sel_old, sel_new)

ast.parse(src)
(WORK / "submission-v9/selector.py").write_text(src)
print("stage 3 OK:", len(src), "bytes")
