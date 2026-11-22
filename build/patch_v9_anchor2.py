#!/usr/bin/env python3
"""Fix the add-run anchor: a '+' run REPLACES the '-' lines it follows, so
its old-file position is old_start + (# context lines before the run), not
counting the deleted lines. A '+' run after context lines (pure insert)
anchors at the last context line (insert after it)."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

old = '''        elif hunk is not None and line[:1] in (" ", "+", "-"):
            if line[0] == "+":
                if not hunk["lines"] or hunk["lines"][-1][0] != "+":
                    # first line of a '+' run: anchor = old lines consumed so far
                    anchor = hunk["old_start"] + sum(
                        1 for t, _ in hunk["lines"] if t in (" ", "-"))
                    if hunk["old_count"] == 0:
                        anchor = hunk["old_start"] - 1
                    hunk["add_runs"].append(anchor)
                hunk["lines"].append(("+", line[1:]))
            else:
                hunk["lines"].append((line[0], line[1:]))'''
new = '''        elif hunk is not None and line[:1] in (" ", "+", "-"):
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
assert src.count(old) == 1, "anchor block not found"
src = src.replace(old, new)
ast.parse(src)
p.write_text(src)
print("add-run anchor fixed")
