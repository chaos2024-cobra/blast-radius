#!/usr/bin/env python3
"""Fix the comment_plain branch cost bug: never union the whole module set
when it exceeds the floor; use the enclosing scope only."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

# V3 branch
v3_old = '''                if comment_plain:
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
v3_new = '''                if comment_plain:
                    # fix 1: a comment-only hunk outside any string still
                    # selects the enclosing scope, or the module floor
                    mt = self.module_tests.get(mod, set())
                    if len(mt) <= 60:
                        tids |= mt
                    else:
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
assert src.count(v3_old) == 1, "v3 comment_plain branch not found"
src = src.replace(v3_old, v3_new)

# V6 branch
v6_old = '''                if comment_plain:
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
v6_new = '''                if comment_plain:
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
'''
assert src.count(v6_old) == 1, "v6 comment_plain branch not found"
src = src.replace(v6_old, v6_new)

ast.parse(src)
p.write_text(src)
print("comment_plain branches fixed")
