#!/usr/bin/env python3
"""Stage 2: rewire V3Engine and V6Engine onto the v9 shared patch layer."""
import ast
import re
from pathlib import Path

WORK = Path("/home/z/my-project/work")
src = (WORK / "submission-v9/selector_v9_stage1.py").read_text()

# ------------------------------------------------------------- V3Engine rewiring
v3_parse = '''    def parse_diff(self, text):
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
                m = re.match(r"@@ -(\\d+)(?:,(\\d+))? \\+(\\d+)(?:,(\\d+))? @@", line)
                hunk = {"old_start": int(m.group(1)), "lines": []}
                files[("new", cur_new)].append(hunk)
            elif hunk is not None and line[:1] in (" ", "+", "-"):
                hunk["lines"].append((line[0], line[1:]))
        return files
'''
v3_parse_new = '''    def parse_diff(self, text):
        return parse_diff9(text)[0]
'''
assert src.count(v3_parse) == 1, "v3 parse_diff not found"
src = src.replace(v3_parse, v3_parse_new)

# V3 hunk_old_range: extend to include add-run anchors (fix 3)
v3_range = '''    @staticmethod
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
'''
v3_range_new = '''    @staticmethod
    def hunk_old_range(hunk):
        ranges = hunk_ranges9(hunk)
        lo = min(r[0] for r in ranges)
        hi = max(r[1] for r in ranges)
        return lo, hi
'''
assert src.count(v3_range) == 1, "v3 hunk_old_range not found"
src = src.replace(v3_range, v3_range_new)

# V3 hunk_comment_only -> shared, plus string-span awareness in the engine
v3_co = '''    @staticmethod
    def hunk_comment_only(hunk):
        adds = [l for t, l in hunk["lines"] if t == "+"]
        dels = [t for t, _ in hunk["lines"] if t == "-"]
        if dels or not adds:
            return False
        ok = lambda s: (not s.strip()) or s.lstrip().startswith("#")
        return all(ok(l) for l in adds)
'''
v3_co_new = '''    @staticmethod
    def hunk_comment_only(hunk):
        return hunk_comment_only9(hunk)
'''
assert src.count(v3_co) == 2, f"expected 2 comment_only defs, got {src.count(v3_co)}"
src = src.replace(v3_co, v3_co_new)

# V3 hunk_string_only -> shared v9 (fix 2)
v3_so = '''    def hunk_string_only(self, mod, hunk):
        dels = [l for t, l in hunk["lines"] if t == "-"]
        if not dels:
            return False
        lo, hi = self.hunk_old_range(hunk)
        return any(s <= lo and hi <= e for s, e in self.docspans.get(mod, []))
'''
v3_so_new = '''    def hunk_string_only(self, mod, hunk):
        return hunk_string_only9(mod, hunk)
'''
assert src.count(v3_so) == 1, "v3 hunk_string_only not found"
src = src.replace(v3_so, v3_so_new)

# V3 select: comment-only hunks are no longer skipped blind; in-string adds
# are live, other comment-only selects enclosing scope or module floor (fix 1)
v3_sel_old = '''                code_hunks = [h for h in hunks if not self.hunk_comment_only(h)]
                if not code_hunks:
                    continue
                if all(self.hunk_string_only(mod, h) for h in code_hunks):
                    continue
'''
v3_sel_new = '''                code_hunks = [h for h in hunks if not self.hunk_comment_only(h)]
                comment_plain = [h for h in hunks
                                 if self.hunk_comment_only(h) and not comment_hunk_live9(mod, h)]
                live_str_hunks = [h for h in hunks
                                  if self.hunk_comment_only(h) and comment_hunk_live9(mod, h)]
                if not code_hunks and not comment_plain and not live_str_hunks:
                    continue
                if (all(self.hunk_string_only(mod, h) for h in code_hunks)
                        and not comment_plain and not live_str_hunks):
                    continue
                hunks_for_scope = code_hunks + live_str_hunks
                if comment_plain:
                    # fix 1: a comment-only hunk outside any string still
                    # selects the enclosing scope, or the module floor
                    mt = self.module_tests.get(mod, set())
                    if len(mt) <= 60:
                        tids |= mt
                    else:
                        for h in comment_plain:
                            lo, hi = self.hunk_old_range(h)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.caller_closure(mod, fn["q"], 1):
                                    tids.update(self.func_tests.get(c, ()))
                            if mlines or classes:
                                tids |= mt if len(mt) <= 60 else self.module_tests.get(mod, set())
'''
assert src.count(v3_sel_old) == 1, "v3 select code_hunks block not found"
src = src.replace(v3_sel_old, v3_sel_new)

# V3 select: hunk loop must iterate hunks_for_scope instead of code_hunks
v3_loop_old = '''                broad = False
                for h in code_hunks:
                    if self.hunk_string_only(mod, h):
                        continue
'''
v3_loop_new = '''                broad = False
                for h in hunks_for_scope:
                    if self.hunk_string_only(mod, h):
                        continue
'''
assert src.count(v3_loop_old) == 1, "v3 hunk loop not found"
src = src.replace(v3_loop_old, v3_loop_new)

# V3 select: pool_child loop also uses hunks_for_scope
v3_pool_old = '''                    touched = False
                    for h in code_hunks:
                        if self.hunk_string_only(mod, h):
                            continue
'''
v3_pool_new = '''                    touched = False
                    for h in hunks_for_scope:
                        if self.hunk_string_only(mod, h):
                            continue
'''
assert src.count(v3_pool_old) == 1, "v3 pool loop not found"
src = src.replace(v3_pool_old, v3_pool_new)

ast.parse(src)
(WORK / "submission-v9/selector_v9_stage2.py").write_text(src)
print("stage 2 OK:", len(src), "bytes")
