#!/usr/bin/env python3
"""Tighten the in-span anchor test: insert-after-old-line-a is inside span
[s, e] iff s <= a < e (no +1 fuzz)."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

old = '''def comment_hunk_live9(path, hunk):
    """A comment-only hunk whose adds fall inside a multi-line string span
    is a live edit of that string (fix 1)."""
    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)
    for a in hunk["add_runs"]:
        if in_strspan(path, a, a + 1):
            return True
    return False'''
new = '''def comment_hunk_live9(path, hunk):
    """A comment-only hunk whose adds fall inside a multi-line string span
    is a live edit of that string (fix 1). Insert-after-old-line a is inside
    span [s, e] iff s <= a < e."""
    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)
    for a in hunk["add_runs"]:
        for s, e, _cls in STRSPANS.get(path, ()):
            if s <= a < e:
                return True
    return False'''
assert src.count(old) == 1, "comment_hunk_live9 not found"
src = src.replace(old, new)

# hunk_string_only9: same fix for the add anchor check
old2 = '''    for a in hunk["add_runs"]:
        if not any(s <= a <= e or s <= a + 1 <= e for s, e, cls in spans if cls in (0, 1)):
            return False'''
new2 = '''    for a in hunk["add_runs"]:
        if not any(s <= a < e for s, e, cls in spans if cls in (0, 1)):
            return False'''
assert src.count(old2) == 1, "add anchor check not found"
src = src.replace(old2, new2)

ast.parse(src)
p.write_text(src)
print("anchor span tests tightened")
