#!/usr/bin/env python3
"""CONSOLIDATED v9 final builder: from the stage3 output state, apply ALL
remaining calibration fixes in one pass (anchors, strcheck2/3, orphan floors,
mod2path, wrappers). Idempotent-ish: reads selector.py, writes selector.py."""
import ast
import base64
import gzip
import json
import re
from pathlib import Path

WORK = Path("/home/z/my-project/work")
P = WORK / "submission-v9/selector.py"
src = P.read_text()
Q3D = '"' * 3
Q3S = "'" * 3
n = 0


def rep(old, new, desc, count=1):
    global src, n
    c = src.count(old)
    assert c == count, f"{desc}: found {c} expected {count}"
    src = src.replace(old, new)
    n += 1
    print(f"  [{n}] {desc}")


# 1. STRSPAN mod2path (inline edit that was never scripted)
rep('''STRSPANS = {k: [tuple(s) for s in v] for k, v in MAPS9["strspans"].items()}''',
    '''STRSPANS = {k: [tuple(s) for s in v] for k, v in MAPS9["strspans"].items()}
_STRSPAN_MOD2PATH = {k[:-3].replace("/", "."): k for k in STRSPANS}''',
    "mod2path map")

rep('''def in_strspan(path, lo, hi):
    """True if [lo, hi] intersects a multi-line string-literal span of path."""
    for s, e, _cls in STRSPANS.get(path, ()):''',
    '''def in_strspan(path, lo, hi):
    """True if [lo, hi] intersects a multi-line string-literal span of path."""
    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)
    for s, e, _cls in STRSPANS.get(path, ()):''',
    "in_strspan normalize")

rep('''    spans = STRSPANS.get(path, ())''',
    '''    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)
    spans = STRSPANS.get(path, ())''',
    "string_only normalize")

rep('''def comment_hunk_live9(path, hunk):''',
    '''def comment_hunk_live9(path, hunk):
    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)''',
    "live9 normalize")

# 2. anchor: slot semantics (anchor2 + anchor3)
rep('''                if not hunk["lines"] or hunk["lines"][-1][0] != "+":
                    # first line of a '+' run: anchor = old lines consumed so far
                    anchor = hunk["old_start"] + sum(
                        1 for t, _ in hunk["lines"] if t in (" ", "-"))
                    if hunk["old_count"] == 0:
                        anchor = hunk["old_start"] - 1
                    hunk["add_runs"].append(anchor)''',
    '''                if not hunk["lines"] or hunk["lines"][-1][0] != "+":
                    # slot = the old-file line the first new line occupies:
                    # old_start + context before the run (dels do NOT advance
                    # it - the run replaces them); for an empty old range
                    # git anchors the insert after line old_start.
                    slot = hunk["old_start"] + sum(
                        1 for t, _ in hunk["lines"] if t == " ")
                    if hunk["old_count"] == 0:
                        slot = hunk["old_start"] + 1 if hunk["old_start"] else 1
                    hunk["add_runs"].append(slot)''',
    "anchor slot semantics")

rep('''    for a in hunk["add_runs"]:
        if in_strspan(path, a, a + 1):
            return True
    return False''',
    '''    for a in hunk["add_runs"]:
        for s, e, _cls in STRSPANS.get(path, ()):
            if s <= a <= e:
                return True
    return False''',
    "live9 slot test")

rep('''        if not any(s <= a <= e or s <= a + 1 <= e for s, e, cls in spans if cls in (0, 1)):''',
    '''        if not any(s <= a <= e for s, e, cls in spans if cls in (0, 1)):''',
    "string_only slot test")

# 3. strcheck2: quote-triple anywhere rejects
rep('''        # inside a string, added text is a new line of the literal: it is
        # live if it would terminate the literal (unescaped quote) or if it
        # is code with '=' or keywords; conservative: only skip if the line
        # contains no '=' , no '(', no 'import', no 'def ', no 'class '
        if any(k in l for k in ("=", "(", "import", "def ", "class ", "return",
                                "raise ", "yield", "@", "for ", "while ", "if ")):
            return False''',
    '''        # inside a docstring/noop span the add is string TEXT unless it
        # terminates the literal early (a quote-triple anywhere in the
        # line), which would turn the rest of the hunk into live code
        if Q3D in l or Q3S in l:
            return False'''.replace("Q3D", repr(Q3D)).replace("Q3S", repr(Q3S)),
    "strcheck quote-anywhere")

# 4. strcheck3: del-side quote-line rule
rep('''    spans = STRSPANS.get(path, ())
    for ln, _l in del_lines:
        if not any(s <= ln <= e and cls in (0, 1) for s, e, cls in spans):
            return False''',
    '''    spans = STRSPANS.get(path, ())
    for ln, _l in del_lines:
        hit = [(s, e) for s, e, cls in spans if cls in (0, 1) and s <= ln <= e]
        if not hit:
            return False
        for s, e in hit:
            if ln == s or ln == e:
                # deleting a quote line breaks the literal: live, not string-only
                return False''',
    "del-side quote rule")

# 5. comment_plain else-arms: orphan floor (final form with before/len check)
rep('''                    else:
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.caller_closure(mod, fn["q"], 1):
                                    tids.update(self.func_tests.get(c, ()))
                            if mlines or classes:
                                tids |= mt if len(mt) <= 60 else self.module_tests.get(mod, set())
''',
    '''                    else:
                        before = len(tids)
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.caller_closure(mod, fn["q"], 1):
                                    tids.update(self.func_tests.get(c, ()))
                        if len(tids) == before:
                            # orphan floor: the enclosing scope has no
                            # attributed tests -> bounded dialect-file set
                            tids |= self._comment_orphan_floor(mod)
''',
    "V3 comment orphan floor")

rep('''                    else:
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
''',
    '''                    else:
                        before = len(tids)
                        for h in comment_plain:
                            ranges = hunk_ranges9(h)
                            lo = max(1, min(r[0] for r in ranges))
                            hi = max(r[1] for r in ranges)
                            funcs, classes, mlines = self.enclosing(mod, lo, hi)
                            for fn in funcs:
                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn['q']}", ()))
                                for c in self.callers.get(f"{mod}:{fn['q']}", ()):
                                    tids.update(TEST_IDS6[i] for i in self.func_tests.get(c, ()))
                        if len(tids) == before:
                            # orphan floor: bounded dialect-file set
                            for i in self._comment_orphan_floor(mod):
                                tids.add(TEST_IDS6[i])
''',
    "V6 comment orphan floor")

# 6. shared comment_orphan_floor (name-based fallback version)
rep('''def comment_orphan_floor(mod, dialect_classes, file_tests):
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
    return out''',
    '''def comment_orphan_floor(mod, dialect_classes, file_tests):
    """Bounded floor for comment-only hunks whose enclosing scope is an
    attribution orphan (no tests, no callers): the module's own dialect test
    file (by dialect class or module name), or tests/dialects/test_dialect.py
    for the root dialect module. Returns test ids."""
    own = [c for c, m in dialect_classes.items() if m == mod]
    paths = [f"tests/dialects/test_{c.lower()}.py" for c in own]
    if not paths:
        tail = mod.rsplit(".", 1)[-1]
        cand = f"tests/dialects/test_{tail}.py"
        paths = [cand] if cand in file_tests else ["tests/dialects/test_dialect.py"]
    out = set()
    for pth in paths:
        out.update(file_tests.get(pth, ()))
    return out''',
    "orphan floor name-based")

# 7. engine wrapper methods (ungated)
anchor = "\ndef hunk_ranges9(hunk):"
assert src.count(anchor) == 1
src = src.replace(anchor, '''

def comment_orphan_floor(mod, dialect_classes, file_tests):
    """Bounded floor for comment-only hunks whose enclosing scope is an
    attribution orphan (no tests, no callers): the module's own dialect test
    file (by dialect class or module name), or tests/dialects/test_dialect.py
    for the root dialect module. Returns test ids."""
    own = [c for c, m in dialect_classes.items() if m == mod]
    paths = [f"tests/dialects/test_{c.lower()}.py" for c in own]
    if not paths:
        tail = mod.rsplit(".", 1)[-1]
        cand = f"tests/dialects/test_{tail}.py"
        paths = [cand] if cand in file_tests else ["tests/dialects/test_dialect.py"]
    out = set()
    for pth in paths:
        out.update(file_tests.get(pth, ()))
    return out
''' + anchor)
print("  [x] shared comment_orphan_floor inserted")

# insert the wrapper methods before each engine's select
method3 = '''
    def _comment_orphan_floor(self, mod):
        return comment_orphan_floor(mod, self.dialect_classes, self._file_tests)
'''
i3 = src.index("class V3Engine:")
i3s = src.index("    def select(self, patch_text, tests_meta):", i3)
src = src[:i3s] + method3 + "\n" + src[i3s:]

method6 = '''
    def _comment_orphan_floor(self, mod):
        ft = comment_orphan_floor(mod, self.dialect_classes, self._file_tests)
        inv = {tid: i for i, tid in enumerate(TEST_IDS6)}
        return sorted({inv[t] for t in ft if t in inv})
'''
i6 = src.index("class V6Engine:")
i6s = src.index("    def select(self, patch_text, tests_meta):", i6)
src = src[:i6s] + method6 + "\n" + src[i6s:]
print("  [x] engine wrappers inserted")

ast.parse(src)
P.write_text(src)
print(f"FINAL selector.py written: {len(src)} bytes, {n} replacements + 3 inserts")
