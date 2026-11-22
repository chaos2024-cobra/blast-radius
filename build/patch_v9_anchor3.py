#!/usr/bin/env python3
"""Encode the add-run SLOT semantics: the old-file line number the first
new line of the run occupies/replaces. Pure inserts get the slot of the old
line they are placed BEFORE (git: empty old range start = line before, so
slot = old_start + 1, clamped at 1). Span membership then is s <= slot <= e."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

old = '''        elif hunk is not None and line[:1] in (" ", "+", "-"):
            if line[0] == "+":
                if not hunk["lines"] or hunk["lines"][-1][0] != "+":
                    # first line of a '+' run. Anchor = the old-file position
                    # the new lines occupy: old_start + context lines before
                    # the run (deleted lines do NOT advance it - the run
                    # replaces them). A pure insert after context line c
                    # anchors at c (insert after it).
                    anchor = hunk["old_start"] + sum(
                        1 for t, _ in hunk["lines"] if t == " ")
                    if hunk["old_count"] == 0 and not hunk["lines"]:
                        # '@@ -N,0 +M @@': insert BEFORE old line N
                        anchor = hunk["old_start"] - 1
                    hunk["add_runs"].append(anchor)
                hunk["lines"].append(("+", line[1:]))
            else:
                hunk["lines"].append((line[0], line[1:]))'''
new = '''        elif hunk is not None and line[:1] in (" ", "+", "-"):
            if line[0] == "+":
                if not hunk["lines"] or hunk["lines"][-1][0] != "+":
                    # slot = the old-file line the first new line occupies.
                    # For a replacement run: the first deleted line's number
                    # (old_start + context before the run; dels don't advance
                    # it). For a pure insert: the old line it goes BEFORE.
                    slot = hunk["old_start"] + sum(
                        1 for t, _ in hunk["lines"] if t == " ")
                    if hunk["old_count"] == 0:
                        # git: empty old range '@@ -N,0' means the insert
                        # sits after line N-1 / before line N+... concretely
                        # '@@ -4,0 +5 @@' = after old 4 = before old 5.
                        slot = hunk["old_start"] + 1 if hunk["old_start"] else 1
                    hunk["add_runs"].append(slot)
                hunk["lines"].append(("+", line[1:]))
            else:
                hunk["lines"].append((line[0], line[1:]))'''
assert src.count(old) == 1, "anchor block not found"
src = src.replace(old, new)

# span membership: slot semantics -> s <= slot <= e for in_strspan-based tests
old2 = '''def comment_hunk_live9(path, hunk):
    """A comment-only hunk whose adds fall inside a multi-line string span
    is a live edit of that string (fix 1). Insert-after-old-line a is inside
    span [s, e] iff s <= a < e."""
    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)
    for a in hunk["add_runs"]:
        for s, e, _cls in STRSPANS.get(path, ()):
            if s <= a < e:
                return True
    return False'''
new2 = '''def comment_hunk_live9(path, hunk):
    """A comment-only hunk whose adds fall inside a multi-line string span
    is a live edit of that string (fix 1). add_runs hold slots: the old-file
    line the new line occupies/replaces; inside span [s, e] iff s <= slot <= e."""
    path = STRSPANS.get(path) and path or _STRSPAN_MOD2PATH.get(path, path)
    for a in hunk["add_runs"]:
        for s, e, _cls in STRSPANS.get(path, ()):
            if s <= a <= e:
                return True
    return False'''
assert src.count(old2) == 1, "comment_hunk_live9 not found"
src = src.replace(old2, new2)

old3 = '''    for a in hunk["add_runs"]:
        if not any(s <= a < e for s, e, cls in spans if cls in (0, 1)):
            return False'''
new3 = '''    for a in hunk["add_runs"]:
        if not any(s <= a <= e for s, e, cls in spans if cls in (0, 1)):
            return False'''
assert src.count(old3) == 1, "string_only anchor check not found"
src = src.replace(old3, new3)

ast.parse(src)
p.write_text(src)
print("slot semantics encoded")
