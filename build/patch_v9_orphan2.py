#!/usr/bin/env python3
"""Add _comment_orphan_floor methods to V3Engine and V6Engine."""
import ast
from pathlib import Path

p = Path("/home/z/my-project/work/submission-v9/selector.py")
src = p.read_text()

method = '''
    def _comment_orphan_floor(self, mod):
        if mod not in self.dialect_classes.values():
            return set()
        return comment_orphan_floor(mod, self.dialect_classes, self._file_tests)
'''

# V3: insert before "def select(self, patch_text, tests_meta):" of V3Engine
# find V3Engine's select by locating the first occurrence after class V3Engine
v3_cls = src.index("class V3Engine:")
v3_sel = src.index("    def select(self, patch_text, tests_meta):", v3_cls)
src = src[:v3_sel] + method + "\n" + src[v3_sel:]

v6_cls = src.index("class V6Engine:")
v6_sel = src.index("    def select(self, patch_text, tests_meta):", v6_cls)
# V6's floor works on indices; adapt: use TEST_IDS6 translation
method6 = '''
    def _comment_orphan_floor(self, mod):
        if mod not in self.dialect_classes.values():
            return ()
        ft = comment_orphan_floor(mod, self.dialect_classes, self._file_tests)
        inv = {v: k for k, v in TEST_IDS6.items()}
        return sorted({inv[t] for t in ft if t in inv})
'''
src = src[:v6_sel] + method6 + "\n" + src[v6_sel:]

ast.parse(src)
p.write_text(src)
print("engine methods added")
