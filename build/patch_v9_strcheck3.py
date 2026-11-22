#!/usr/bin/env python3
"""Fix the del-side rule of hunk_string_only9: deleting a span's quote line
(the first or last line of a docstring/noop span) breaks the literal, so
such hunks are live. Dels strictly inside the span are safe string edits."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

old = '''    spans = STRSPANS.get(path, ())
    for ln, _l in del_lines:
        if not any(s <= ln <= e and cls in (0, 1) for s, e, cls in spans):
            return False'''
new = '''    spans = STRSPANS.get(path, ())
    for ln, _l in del_lines:
        hit = [(s, e) for s, e, cls in spans if cls in (0, 1) and s <= ln <= e]
        if not hit:
            return False
        for s, e in hit:
            if ln == s or ln == e:
                # deleting a quote line (opening or closing) breaks the
                # literal: the hunk is live, not a string-only edit
                return False'''
assert src.count(old) == 1, "del-side rule not found"
src = src.replace(old, new)
ast.parse(src)
p.write_text(src)
print("del-side quote-line rule added")
