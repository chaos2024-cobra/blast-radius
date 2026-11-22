#!/usr/bin/env python3
"""Tighten the added-line content check: any quote-triple inside an added
line can terminate the literal early, turning the remainder into code."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

Q3D = '"' * 3
Q3S = "'" * 3

old = (
    "    for l in adds:\n"
    "        st = l.strip()\n"
    "        if not st:\n"
    "            continue\n"
    "        # inside a docstring/noop span the add is string TEXT unless it ends\n"
    "        # the literal early (an unescaped quote run), which would turn the\n"
    "        # remaining lines into code\n"
    "        if st.startswith(%r) or st.startswith(%r):\n"
    "            return False\n"
    "    return True" % (Q3D, Q3S)
)
new = (
    "    for l in adds:\n"
    "        # inside a docstring/noop span the add is string TEXT unless it\n"
    "        # terminates the literal early (a quote-triple anywhere in the\n"
    "        # line), which would turn the rest of the hunk into live code\n"
    "        if %r in l or %r in l:\n"
    "            return False\n"
    "    return True" % (Q3D, Q3S)
)
assert src.count(old) == 1, "content check not found"
src = src.replace(old, new)
ast.parse(src)
p.write_text(src)
print("content check tightened")
