#!/usr/bin/env python3
"""Patch the string-content check in selector.py (fix 2 cost calibration)."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

Q3D = '"' * 3
Q3S = "'" * 3

old = '''    for l in adds:
        st = l.strip()
        if not st:
            continue
        # inside a string, added text is a new line of the literal: it is
        # live if it would terminate the literal (unescaped quote) or if it
        # is code with '=' or keywords; conservative: only skip if the line
        # contains no '=' , no '(', no 'import', no 'def ', no 'class '
        if any(k in l for k in ("=", "(", "import", "def ", "class ", "return",
                                "raise ", "yield", "@", "for ", "while ", "if ")):
            return False
    return True'''
new = (
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
assert src.count(old) == 1, "content check not found"
src = src.replace(old, new)
ast.parse(src)
p.write_text(src)
print("hunk_string_only9 content check fixed")
