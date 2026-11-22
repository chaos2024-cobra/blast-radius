#!/usr/bin/env python3
"""FINAL v9 fixer: applies all remaining fixes to selector.py in one pass.
Reads selector.py, applies text replacements, writes it back. Run once."""
import ast
from pathlib import Path

P = Path("/home/z/my-project/work/submission-v9/selector.py")
src = P.read_text()
applied = []


def rep(old, new, desc):
    global src
    c = src.count(old)
    assert c == 1, f"{desc}: found {c}"
    src = src.replace(old, new)
    applied.append(desc)


Q3D = chr(34) * 3
Q3S = chr(39) * 3

# --- 1. mod2path normalization ---
rep('STRSPANS = {k: [tuple(s) for s in v] for k, v in MAPS9["strspans"].items()}',
    'STRSPANS = {k: [tuple(s) for s in v] for k, v in MAPS9["strspans"].items()}\n'
    '_STRSPAN_MOD2PATH = {k[:-3].replace("/", "."): k for k in STRSPANS}',
    "mod2path")

rep('def in_strspan(path, lo, hi):\n    """True if [lo, hi] intersects a multi-line string-literal span of path."""\n    for s, e, _cls in STRSPANS.get(path, ()):',
    'def in_strspan(path, lo, hi):\n    """True if [lo, hi] intersects a multi-line string-literal span of path."""\n'
    '    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)\n'
    '    for s, e, _cls in STRSPANS.get(path, ()):',
    "in_strspan norm")

rep('    spans = STRSPANS.get(path, ())\n    for ln, _l in del_lines:',
    '    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)\n'
    '    spans = STRSPANS.get(path, ())\n    for ln, _l in del_lines:',
    "string_only norm")

rep('def comment_hunk_live9(path, hunk):\n    """A comment-only hunk whose adds fall inside a multi-line string span\n    is a live edit of that string (fix 1)."""',
    'def comment_hunk_live9(path, hunk):\n    """A comment-only hunk whose adds fall inside a multi-line string span\n    is a live edit of that string (fix 1)."""\n'
    '    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)',
    "live9 norm")

# --- 2. slot anchors ---
old_anchor = ('                if not hunk["lines"] or hunk["lines"][-1][0] != "+":\n'
              '                    # first line of a \'+\' run: anchor = old lines consumed so far\n'
              '                    anchor = hunk["old_start"] + sum(\n'
              '                        1 for t, _ in hunk["lines"] if t in (" ", "-"))\n'
              '                    if hunk["old_count"] == 0:\n'
              '                        anchor = hunk["old_start"] - 1\n'
              '                    hunk["add_runs"].append(anchor)')
new_anchor = ('                if not hunk["lines"] or hunk["lines"][-1][0] != "+":\n'
              '                    # slot = the old-file line the first new line occupies:\n'
              '                    # old_start + context before the run (deleted lines do\n'
              '                    # NOT advance it - the run replaces them); an empty old\n'
              '                    # range "@@ -N,0" means the insert sits after line N.\n'
              '                    slot = hunk["old_start"] + sum(\n'
              '                        1 for t, _ in hunk["lines"] if t == " ")\n'
              '                    if hunk["old_count"] == 0:\n'
              '                        slot = hunk["old_start"] + 1 if hunk["old_start"] else 1\n'
              '                    hunk["add_runs"].append(slot)')
rep(old_anchor, new_anchor, "slot anchors")

rep('    for a in hunk["add_runs"]:\n        if in_strspan(path, a, a + 1):\n            return True\n    return False',
    '    for a in hunk["add_runs"]:\n        for s, e, _cls in STRSPANS.get(path, ()):\n            if s <= a <= e:\n                return True\n    return False',
    "live9 slot test")

rep('        if not any(s <= a <= e or s <= a + 1 <= e for s, e, cls in spans if cls in (0, 1)):',
    '        if not any(s <= a <= e for s, e, cls in spans if cls in (0, 1)):',
    "string_only slot test")

# --- 3. strcheck quote-anywhere ---
old_sc = ('        # inside a docstring/noop span the add is string TEXT unless it ends\n'
          '        # the literal early (an unescaped quote run), which would turn the\n'
          '        # remaining lines into code\n'
          '        if st.startswith(' + repr(Q3D) + ') or st.startswith(' + repr(Q3S) + '):\n'
          '            return False\n'
          '    return True')
new_sc = ('        # inside a docstring/noop span the add is string TEXT unless it\n'
          '        # terminates the literal early (a quote-triple anywhere in the\n'
          '        # line), which would turn the rest of the hunk into live code\n'
          '        if ' + repr(Q3D) + ' in l or ' + repr(Q3S) + ' in l:\n'
          '            return False\n'
          '    return True')
rep(old_sc, new_sc, "strcheck quote-anywhere")

# --- 4. del-side quote rule ---
rep('    for ln, _l in del_lines:\n        if not any(s <= ln <= e and cls in (0, 1) for s, e, cls in spans):\n            return False',
    '    for ln, _l in del_lines:\n        hit = [(s, e) for s, e, cls in spans if cls in (0, 1) and s <= ln <= e]\n'
    '        if not hit:\n            return False\n'
    '        for s, e in hit:\n'
    '            if ln == s or ln == e:\n'
    '                # deleting a quote line breaks the literal: live\n'
    '                return False',
    "del-side quote rule")

# --- 5. V3 comment orphan floor ---
rep('                    if len(mt) <= 60:\n                        tids |= mt\n'
    '                    else:\n'
    '                        for h in comment_plain:\n'
    '                            ranges = hunk_ranges9(h)\n'
    '                            lo = max(1, min(r[0] for r in ranges))\n'
    '                            hi = max(r[1] for r in ranges)\n'
    '                            funcs, classes, mlines = self.enclosing(mod, lo, hi)\n'
    '                            for fn in funcs:\n'
    '                                tids.update(self.func_tests.get(f"{mod}:{fn[\'q\']}", ()))\n'
    '                                for c in self.caller_closure(mod, fn["q"], 1):\n'
    '                                    tids.update(self.func_tests.get(c, ()))\n',
    '                    if len(mt) <= 60:\n                        tids |= mt\n'
    '                    else:\n'
    '                        before = len(tids)\n'
    '                        for h in comment_plain:\n'
    '                            ranges = hunk_ranges9(h)\n'
    '                            lo = max(1, min(r[0] for r in ranges))\n'
    '                            hi = max(r[1] for r in ranges)\n'
    '                            funcs, classes, mlines = self.enclosing(mod, lo, hi)\n'
    '                            for fn in funcs:\n'
    '                                tids.update(self.func_tests.get(f"{mod}:{fn[\'q\']}", ()))\n'
    '                                for c in self.caller_closure(mod, fn["q"], 1):\n'
    '                                    tids.update(self.func_tests.get(c, ()))\n'
    '                        if len(tids) == before:\n'
    '                            # orphan floor: the enclosing scope has no\n'
    '                            # attributed tests -> bounded dialect-file set\n'
    '                            tids |= self._comment_orphan_floor(mod)\n',
    "V3 orphan floor")

# --- 6. V6 comment orphan floor ---
rep('                            for fn in funcs:\n'
    '                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn[\'q\']}", ()))\n'
    '                                for c in self.callers.get(f"{mod}:{fn[\'q\']}", ()):'
    '\n                                    tids.update(TEST_IDS6[i] for i in self.func_tests.get(c, ()))\n'
    '                for h in hunks_for_scope:',
    '                            for fn in funcs:\n'
    '                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn[\'q\']}", ()))\n'
    '                                for c in self.callers.get(f"{mod}:{fn[\'q\']}", ()):'
    '\n                                    tids.update(TEST_IDS6[i] for i in self.func_tests.get(c, ()))\n'
    '                        if len(tids) == before:\n'
    '                            # orphan floor: bounded dialect-file set\n'
    '                            for i in self._comment_orphan_floor(mod):\n'
    '                                tids.add(TEST_IDS6[i])\n'
    '                for h in hunks_for_scope:',
    "V6 orphan floor arm")

# V6 needs the before= line too (its else-arm starts above the funcs loop)
rep('                    else:\n'
    '                        for h in comment_plain:\n'
    '                            ranges = hunk_ranges9(h)\n'
    '                            lo = max(1, min(r[0] for r in ranges))\n'
    '                            hi = max(r[1] for r in ranges)\n'
    '                            funcs, classes, mlines = self.enclosing(mod, lo, hi)\n'
    '                            for fn in funcs:\n'
    '                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn[\'q\']}", ()))',
    '                    else:\n'
    '                        before = len(tids)\n'
    '                        for h in comment_plain:\n'
    '                            ranges = hunk_ranges9(h)\n'
    '                            lo = max(1, min(r[0] for r in ranges))\n'
    '                            hi = max(r[1] for r in ranges)\n'
    '                            funcs, classes, mlines = self.enclosing(mod, lo, hi)\n'
    '                            for fn in funcs:\n'
    '                                tids.update(TEST_IDS6[i] for i in self.func_tests.get(f"{mod}:{fn[\'q\']}", ()))',
    "V6 before line")

# --- 7. shared comment_orphan_floor + engine wrappers ---
FLOOR = (
    "\n\ndef comment_orphan_floor(mod, dialect_classes, file_tests):\n"
    '    """Bounded floor for comment-only hunks whose enclosing scope is an\n'
    '    attribution orphan (no tests, no callers): the module\'s own dialect\n'
    '    test file (by dialect class or module name), else the root dialect\n'
    '    test file. Returns test ids."""\n'
    '    own = [c for c, m in dialect_classes.items() if m == mod]\n'
    '    paths = [f"tests/dialects/test_{c.lower()}.py" for c in own]\n'
    "    if not paths:\n"
    '        tail = mod.rsplit(".", 1)[-1]\n'
    '        cand = f"tests/dialects/test_{tail}.py"\n'
    '        paths = [cand] if cand in file_tests else ["tests/dialects/test_dialect.py"]\n'
    "    out = set()\n"
    "    for pth in paths:\n"
    "        out.update(file_tests.get(pth, ()))\n"
    "    return out\n"
)
anchor = "\ndef hunk_ranges9(hunk):"
assert src.count(anchor) == 1
src = src.replace(anchor, FLOOR + anchor)
applied.append("shared floor fn")

m3 = ('\n    def _comment_orphan_floor(self, mod):\n'
      '        return comment_orphan_floor(mod, self.dialect_classes, self._file_tests)\n')
i3 = src.index("class V3Engine:")
i3s = src.index("    def select(self, patch_text, tests_meta):", i3)
src = src[:i3s] + m3 + "\n" + src[i3s:]
applied.append("V3 wrapper")

m6 = ('\n    def _comment_orphan_floor(self, mod):\n'
      '        ft = comment_orphan_floor(mod, self.dialect_classes, self._file_tests)\n'
      '        inv = {tid: i for i, tid in enumerate(TEST_IDS6)}\n'
      '        return sorted({inv[t] for t in ft if t in inv})\n')
i6 = src.index("class V6Engine:")
i6s = src.index("    def select(self, patch_text, tests_meta):", i6)
src = src[:i6s] + m6 + "\n" + src[i6s:]
applied.append("V6 wrapper")

ast.parse(src)
P.write_text(src)
print(f"applied {len(applied)} fixes: {applied}")
