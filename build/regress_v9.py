#!/usr/bin/env python3
"""Regression: v9 vs v8 misses + simulated seconds on the labeled sets."""
import contextlib
import heapq
import importlib.util
import io
import json
from pathlib import Path

WORK = Path("/home/z/my-project/work")
TESTS = json.loads((WORK / "blast-radius-sample/sample/tests.json").read_text())["tests"]
DUR = {t["id"]: t["seconds"] for t in TESTS}
N2I = {t["number"]: t["id"] for t in TESTS}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            spec.loader.exec_module(m)
        except SystemExit:
            pass
    return m.Selector()


def pack(ids):
    nums = sorted((DUR[i] for i in ids), reverse=True)
    best = None
    for k in range(1, 9):
        heaps = [(0.0, w) for w in range(k)]
        heapq.heapify(heaps)
        for d in nums:
            l, w = heapq.heappop(heaps)
            heapq.heappush(heaps, (l + d, w))
        c = max(h[0] for h in heaps) + 2 * k
        best = c if best is None else min(best, c)
    return best


def main():
    S = {"v8": load(WORK / "submission-v8/selector.py", "i8"),
         "v9": load(WORK / "submission-v9/selector.py", "i9")}

    SAMPLE_ANS = json.loads((WORK / "blast-radius-sample/sample/answers.json").read_text())["commits"]
    MUTANT_ANS = json.loads((WORK / "mutants/labels.json").read_text())
    CO_ANS = {}
    for lf in (WORK / "realset/labels_codeonly").glob("*.json"):
        d = json.loads(lf.read_text())
        if not d.get("patch_failed") and not d.get("run_failed"):
            CO_ANS[lf.stem] = d.get("failing", [])

    def failing_of(label, stem):
        if label == "sample":
            return {N2I[n] for n in SAMPLE_ANS.get(stem, {}).get("failing", [])}
        if label == "mutants":
            return {f for f in MUTANT_ANS.get(stem, {}).get("failing", []) if f in DUR}
        return {f for f in CO_ANS.get(stem, []) if f in DUR}

    for label, cdir in [
        ("sample", WORK / "blast-radius-sample/sample/commits"),
        ("mutants", WORK / "mutants"),
        ("codeonly", WORK / "realset/commits_codeonly"),
    ]:
        t8 = t9 = 0.0
        m8 = m9 = sup = n = 0
        miss_names = []
        for p in sorted(cdir.glob("*.patch")):
            txt = p.read_text(errors="replace")
            s8 = S["v8"].select(txt, TESTS)
            s9 = S["v9"].select(txt, TESTS)
            n += 1
            sup += s8 <= s9
            t8 += pack(s8)
            t9 += pack(s9)
            fail = failing_of(label, p.stem)
            m8 += len(fail - s8)
            m9v = len(fail - s9)
            m9 += m9v
            if m9v:
                miss_names.append((p.stem, sorted(fail - s9)[:3]))
        print(f"{label}: {n} commits | v8 misses={m8} -> v9 misses={m9} {miss_names[:4]} | "
              f"v8 {t8:.1f}s -> v9 {t9:.1f}s (+{100 * (t9 - t8) / max(t8, 0.1):.2f}%) | "
              f"v9 superset of v8: {sup}/{n}")


if __name__ == "__main__":
    main()
