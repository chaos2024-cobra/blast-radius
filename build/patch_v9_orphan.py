#!/usr/bin/env python3
"""Orphan floor for comment-only hunks: when the enclosing scope yields no
tests (attribution orphan in a big module), select a bounded dialect-file set
(the module's own dialect test file, or test_dialect.py for the root dialect
module), else the <=60 module floor. Never the whole module set."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

# ---- V3 branch: append orphan fallback to the comment_plain else-arm ----
v3_old = '''                    else:
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.caller_closure(mod, fn["q"], 1):
                                    tids.update(self.func_tests.get(c, ()))
'''
v3_new = '''                    else:
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.caller_closure(mod, fn["q"], 1):
                                    tids.update(self.func_tests.get(c, ()))
                            if not funcs:
                                # orphan floor: attribution orphan in a big
                                # module -> bounded dialect-file set
                                tids |= self._comment_orphan_floor(mod)
'''
assert src.count(v3_old) == 1, "v3 comment else-arm not found"
src = src.replace(v3_old, v3_new)

# ---- V6 branch: same ----
v6_old = '''                    else:
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.callers.get(f"{mod}:{fn['q']}", ()):
                                    tids.update(TEST_IDS6[i] for i in self.func_tests.get(c, ()))
'''
v6_new = '''                    else:
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.callers.get(f"{mod}:{fn['q']}", ()):
                                    tids.update(TEST_IDS6[i] for i in self.func_tests.get(c, ()))
                            if not funcs:
                                # orphan floor: bounded dialect-file set
                                for i in self._comment_orphan_floor(mod):
                                    tids.add(TEST_IDS6[i])
'''
assert src.count(v6_old) == 1, "v6 comment else-arm not found"
src = src.replace(v6_old, v6_new)

# ---- add the helper to both engines (module-level, shared) ----
helper = '''

def comment_orphan_floor(mod, dialect_classes, file_tests):
    """Bounded floor for comment-only hunks whose enclosing scope is an
    attribution orphan (no tests, no callers): the module's own dialect test
    file, or tests/dialects/test_dialect.py for the root dialect module.
    Returns test-file paths (V3) - indices resolved by the caller."""
    own = [c for c, m in dialect_classes.items() if m == mod]
    paths = []
    for c in own:
        paths.append(f"tests/dialects/test_{c.lower()}.py")
    if not paths:
        paths.append("tests/dialects/test_dialect.py")
    out = set()
    for pth in paths:
        out.update(file_tests.get(pth, ()))
    return out
'''
anchor = "\ndef hunk_ranges9(hunk):"
assert src.count(anchor) == 1
src = src.replace(anchor, helper + anchor)

ast.parse(src)
p.write_text(src)
print("orphan floor added")
