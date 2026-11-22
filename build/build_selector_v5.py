#!/usr/bin/env python3
"""Build v5 submission: reuse v4's compacted maps blob + add keyword map.
Reads the v4 selector.py blob, injects it into the v5 template."""
import base64
import gzip
import json
import re
from pathlib import Path

V4 = Path("/home/z/my-project/download/submission-v4/selector.py")
TEMPLATE = Path("/home/z/my-project/scripts/selector_v5_template.py")
OUT_DIR = Path("/home/z/my-project/work/submission-v5")
OUT_DIR.mkdir(parents=True, exist_ok=True)

v4_src = V4.read_text()
mm = re.search(r"_MAPS_BLOB = \(\n(.*?)\n\)", v4_src, re.S)
assert mm, "blob not found in v4"
blob = "".join(re.findall(r'"([^"]*)"', mm.group(1)))

maps = json.loads(gzip.decompress(base64.b85decode(blob)))
print("v4 map keys:", sorted(maps.keys()))

kw = json.loads(Path("/home/z/my-project/work/maps/keyword_map.json").read_text())
maps["keywords"] = kw
print("added keywords:", len(kw))

new_blob = base64.b85encode(gzip.compress(json.dumps(maps).encode(), 9)).decode()
# wrap at 100 cols
wrapped = "\n".join(new_blob[i:i+100] for i in range(0, len(new_blob), 100))

tpl = TEMPLATE.read_text()
# quote each wrapped line as a Python string literal
quoted = "\n".join(f'    "{line}"' for line in wrapped.split("\n"))
out = tpl.replace("__BLOB__", quoted)
(OUT_DIR / "selector.py").write_text(out)
print("written", OUT_DIR / "selector.py", len(out), "bytes")

# syntax check
import ast
ast.parse(out)
print("syntax ok")
