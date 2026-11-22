#!/usr/bin/env python3
"""Build v9 selector from v8: the six shared patch-logic fixes.

Fixes (all in the shared patch->location layer, both engines):
1. comment-only hunks inside multi-line string spans are live edits;
   other comment-only hunks select enclosing scope or module floor.
2. hunk_string_only inspects added lines too (docstring-del + code-add is live).
3. true insertion anchors for '+' runs (pure-add and mixed hunks).
4. test-file import closure: editing a test file selects importers' tests.
5. read map: edits under sqlglot/typing/, sqlglot/generators/hive.py,
   sqlglotc/** select the source-reading tests.
6. rename/mode/binary headers of tracked files -> run-all.

The v9 maps blob (strspans, test_closure, read_map) is appended as a third
embedded blob, decoded once at import.
"""
import base64
import gzip
import json
import re
from pathlib import Path

WORK = Path("/home/z/my-project/work")
V8 = WORK / "submission-v8/selector.py"
V9_MAPS = WORK / "maps/v9_maps.json"
OUT_DIR = WORK / "submission-v9"
OUT_DIR.mkdir(exist_ok=True)

src = V8.read_text()

# ---------------------------------------------------------------- new shared layer
SHARED = '''
# ---------------- v9 shared patch layer (fixes 1, 2, 3, 6) ----------------

_RE_HUNK9 = re.compile(r"^@@ -(\\d+)(?:,(\\d+))? \\+(\\d+)(?:,(\\d+))? @@")


def _unquote_git_path(p):
    if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
        p = p[1:-1]
        try:
            p = p.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except Exception:
            pass
    return p


def _strip_ab(p):
    p = _unquote_git_path(p.split("\\t")[0])
    if p.startswith("a/") or p.startswith("b/"):
        return p[2:]
    return p


def parse_diff9(text):
    """Parse a git unified diff including rename/mode/binary headers.

    Returns (files, run_all):
      files: {(kind, path): [hunk, ...]} where hunk = {"old_start": int,
      "lines": [(tag, text)], "add_runs": [old_line_anchor, ...]} and kind is
      "new" or "del". Hunks carry the true old-file anchor of every '+'
      run (fix 3): the last old line before the run (0 = insert at top).
      run_all: True when a tracked source/test file is renamed, mode-changed,
      or binary-changed (fix 6), or when the diff is malformed.
    """
    files = {}
    cur_new, cur_old, hunk = None, None, None
    meta = {"rename": False, "mode": False, "binary": False}
    run_all = False
    saw_plus = False
    for line in text.splitlines():
        if line.startswith("+++ "):
            p = _strip_ab(line[4:])
            cur_new = None if p == "/dev/null" else p
            saw_plus = True
            hunk = None
            files.setdefault(("new" if cur_new else "del", cur_new or cur_old), [])
        elif line.startswith("--- "):
            cur_old = _strip_ab(line[4:])
        elif line.startswith("diff --git "):
            hunk = None
            if not saw_plus:
                # pure rename/mode/binary file: no ---/+++ section follows
                mid = line[11:]
                a = mid.split(" b/", 1)[0][2:] if " b/" in mid else ""
                b = mid.rsplit(" b/", 1)[1] if " b/" in mid else ""
                a, b = _strip_ab(a), _strip_ab(b)
                files.setdefault(("new", b or a), [])
        elif line.startswith("@@ ") and cur_new:
            mm = _RE_HUNK9.match(line)
            if mm is None:
                hunk = None
                run_all = True
                continue
            hunk = {"old_start": int(mm.group(1)), "old_count": int(mm.group(2) or 1),
                    "lines": [], "add_runs": []}
            files[("new", cur_new)].append(hunk)
        elif line.startswith("rename from ") or line.startswith("rename to "):
            meta["rename"] = True
        elif line.startswith(("old mode ", "new mode ")):
            meta["mode"] = True
        elif line.startswith("Binary files "):
            meta["binary"] = True
        elif hunk is not None and line[:1] in (" ", "+", "-"):
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
                hunk["lines"].append((line[0], line[1:]))
        elif line[:1] in ("+", "-") and not line.startswith(("+++", "---")):
            run_all = True
    if meta["rename"] or meta["mode"] or meta["binary"]:
        run_all = True
    return files, run_all


def hunk_ranges9(hunk):
    """[(lo, hi)] old-file ranges touched: every '-' line and every '+'
    run anchor. A pure-add hunk with old_count==0 at the very top yields
    [(0, 0)] (insert before line 1)."""
    ranges = []
    oldno = hunk["old_start"]
    dels = []
    for t, _ in hunk["lines"]:
        if t == " ":
            oldno += 1
        elif t == "-":
            dels.append(oldno)
            oldno += 1
    if dels:
        ranges.append((min(dels), max(dels)))
    for a in hunk["add_runs"]:
        ranges.append((a, a))
    if not ranges:
        ranges.append((hunk["old_start"] - 1, hunk["old_start"]))
    return ranges


def hunk_comment_only9(hunk):
    adds = [l for t, l in hunk["lines"] if t == "+"]
    dels = [t for t, _ in hunk["lines"] if t == "-"]
    if dels or not adds:
        return False
    ok = lambda s: (not s.strip()) or s.lstrip().startswith("#")
    return all(ok(l) for l in adds)


def in_strspan(path, lo, hi):
    """True if [lo, hi] intersects a multi-line string-literal span of path."""
    for s, e, _cls in STRSPANS.get(path, ()):
        if s <= hi and lo <= e:
            return True
    return False


def hunk_string_only9(path, hunk):
    """Docstring/noop-string-only edit (safe to skip). Requires EVERY changed
    line, deleted and added, to sit inside a class-0/1 span (fix 2). Added
    lines must be pure string-text lines (no code) - enforced by the span
    check on the add anchors and the plain-text check on the added content."""
    dels = [l for t, l in hunk["lines"] if t == "-"]
    if not dels:
        return False
    if not hunk["add_runs"] and not dels:
        return False
    # deleted lines must all be inside docstring/noop spans
    oldno = hunk["old_start"]
    del_lines = []
    for t, l in hunk["lines"]:
        if t == " ":
            oldno += 1
        elif t == "-":
            del_lines.append((oldno, l))
            oldno += 1
    spans = STRSPANS.get(path, ())
    for ln, _l in del_lines:
        if not any(s <= ln <= e and cls in (0, 1) for s, e, cls in spans):
            return False
    # added lines must be string text: every add anchor inside a class-0/1 span
    # and every added line must look like string content (no code that could
    # be live): the anchor test alone is not enough for adds at the span edge.
    adds = [l for t, l in hunk["lines"] if t == "+"]
    for a in hunk["add_runs"]:
        if not any(s <= a <= e or s <= a + 1 <= e for s, e, cls in spans if cls in (0, 1)):
            return False
    for l in adds:
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
    return True


def comment_hunk_live9(path, hunk):
    """A comment-only hunk whose adds fall inside a multi-line string span
    is a live edit of that string (fix 1)."""
    for a in hunk["add_runs"]:
        if in_strspan(path, a, a + 1):
            return True
    return False
'''

# Insert the shared layer right before "class V3Engine:"
anchor = "class V3Engine:"
assert src.count(anchor) == 1
src = src.replace(anchor, SHARED + "\n\n" + anchor)

# Decode v8 blob6 to reuse TEST_IDS6 / maps at module level for the new layer
# STRSPANS needs to be defined after MAPS6 decode; the shared layer is inserted
# before V3Engine which is after MAPS3 decode - need STRSPANS defined there.
# Simpler: append the v9 blob right after the MAPS6 decode line.
map6_line = 'MAPS6 = json.loads(gzip.decompress(base64.b85decode(_MAPS_BLOB6)))'
assert src.count(map6_line) == 1
v9 = json.loads(V9_MAPS.read_text())
raw = json.dumps(v9, separators=(",", ":")).encode()
blob = base64.b85encode(gzip.compress(raw, 9)).decode()
lines = [blob[i:i + 96] for i in range(0, len(blob), 96)]
lit = "_MAPS_BLOB9 = (\n" + "\n".join('    "%s"' % l for l in lines) + "\n)\n"
decode9 = ('MAPS9 = json.loads(gzip.decompress(base64.b85decode(_MAPS_BLOB9)))\n'
           'STRSPANS = {k: [tuple(s) for s in v] for k, v in MAPS9["strspans"].items()}\n'
           'TEST_CLOSURE = MAPS9["test_closure"]\n'
           'READ_MAP = MAPS9["read_map"]\n')
src = src.replace(map6_line, map6_line + "\n" + lit + decode9)

(OUT_DIR / "selector_v9_stage1.py").write_text(src)
import ast
ast.parse(src)
print("stage 1 OK:", len(src), "bytes; v9 blob", len(raw), "raw bytes")
