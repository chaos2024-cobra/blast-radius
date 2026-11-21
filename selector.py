"""Blast Radius selector v1.1 (conservative, self-contained).

Validated on the 30 sample commits: Simulated 648.2 s, 0 misses (starter
baseline: 1614.1 s). Pure-stdlib Python; runtime CPU is well under a second.

Strategy:
- comment-only patches in non-test code  -> run nothing (samples: 3/3 harmless).
- fixture-only patches under tests/fixtures/ -> run exactly the test(s) mapped
  to that fixture file (map embedded below; validated 11/11 on samples).
- everything else (code, test-code, mixed, unparseable) -> run ALL tests split
  across up to 8 workers by LPT with worker count k minimizing max-load + 2k.
  Recall-safe fallback: cannot miss.
"""
from __future__ import annotations

import base64
import json
import sys
import traceback
import zlib
from pathlib import Path

DATA = Path("/data")
MAX_WORKERS = 8
WORKER_COST = 2.0

# fixture file (relative to tests/fixtures/) -> [test id or test file]
# Built from the pinned sqlglot commit eb11aec4be8cb2122afe713a4816662c3f0fb2fa:
# optimizer fixtures via check_file(...) call sites in tests/test_optimizer.py,
# tpc csvs via the executor tests, others by name reference in test files.
_FIXTURE_MAP_BLOB = (
    "c-p;~Pm|gp7{>2@ijL>jy?gC==uD?Qw71R<gYar_2p}(L-A=!IAz57|iEfjSOAG{_A1{9%kUz7z;Gmpvrv>iieEH$mZ0-OZK"
    "E)?-mMSzt!or;9A8$S(Sl*Its109Y{_Ht?*`Zd3y5i~Um(QzjKUNLGxj?f9bGV3!$5pg(q7*M+pQuvWQ3qt>6>~x>Yz^yDAx"
    "JEjKSS2{bIx*EmADbYPK-Ml7>uYyQUs$)E5WD?sh)sqiF@)yC<j(iNfa%6hjT|Ug@X()Du&KnZ{Dp)H)5xS8qTOxx*_P-dk<"
    "EO5Y3xZiW8`1HDBmjhH@YwE|Gq`R;?6Rg58b~TPl-cl(yxNd48$iDNJgU+X%2Y6mqSV0?%)QCf%(_7s3uyPj!vQg6pG-tBHg"
    "_DH5ioFMEg4E!c@R7I<)w{+`gHbO)w)FldixkxFTMA0pqJ26knl@&H1D`yN6LABT34dx$*>SH!{sMKG1I=(nnm8o{~D+sTz-"
    "4jsr^q>0dO46ADBq#zWfiS6jAf3BX&I>SD33`Ywo34?e7STH;+wl56^{08QoenYHYGtRqVl?=O+VH`U#j!L}^2hJ@_!Li`H4"
    "NG_e6w)}wa)LZMU1lDiR|cV+Tfj-;AskA*wbT@XWd-thcH*MU$tbi(D7560MI{sqy-3zn@w}Kra0hKqSs@Oxj!xL~OC7iToD"
    "d5X^AfNShLoCTwa~CQZGONM4qbz?`*TQUx0m{-^$2h!-%<HUEmZ!LvxP@kXW!i;V}f}TG1+HL1qr^FjZutwa46adQYaY7yE_"
    "Pqj%3>%`r7h%cF(47sC9YO(HoPGU}2lJ|6}W=$T>%==l?pVSE~B+H1syDp;Lq6xCtsB-{RM$gXg{H%76Ae`}+@5knuJ")

FIXTURE_MAP = json.loads(zlib.decompress(base64.b85decode(_FIXTURE_MAP_BLOB)))


def parse_patch(text: str) -> dict:
    """Return {path: {"adds": [...], "dels": [...]}} from a unified diff.

    Binary files and renames produce no +/- lines; they still register the path.
    """
    files: dict = {}
    cur = None
    try:
        for line in text.splitlines():
            if line.startswith("+++ b/"):
                cur = line[6:]
                files.setdefault(cur, {"adds": [], "dels": []})
            elif line.startswith("--- a/"):
                pass
            elif cur is not None:
                if line.startswith("+"):
                    files[cur]["adds"].append(line[1:])
                elif line.startswith("-"):
                    files[cur]["dels"].append(line[1:])
    except Exception:
        return {}
    return files


def is_comment_line(line: str) -> bool:
    s = line.strip()
    return (not s) or s.startswith("#") or s.startswith("//")


def classify(files: dict) -> set:
    kinds = set()
    for path, ch in files.items():
        if path.startswith("tests/fixtures/"):
            kinds.add("fixture")
        elif path.startswith("tests/") or path == "tests":
            kinds.add("test-code")
        elif path.startswith("sqlglot/"):
            if ch["adds"] and all(is_comment_line(l) for l in ch["adds"]) and not ch["dels"]:
                kinds.add("comment")
            else:
                kinds.add("code")
        else:
            kinds.add("other")
    return kinds


def select(data: Path) -> list:
    meta = json.loads((data / "tests.json").read_text())["tests"]
    i2n = {t["id"]: t["number"] for t in meta}
    sec = {t["number"]: t["seconds"] for t in meta}
    all_nums = [t["number"] for t in meta]

    lines = []
    for pf in sorted((data / "commits").glob("*.patch")):
        try:
            files = parse_patch(pf.read_text(errors="replace"))
            kinds = classify(files)
            if not files:
                kinds = {"other"}  # unparseable/empty: run everything
            if kinds == {"comment"}:
                workers = []
            elif "fixture" in kinds and not (kinds & {"code", "test-code", "other"}):
                nums = set()
                unmapped = False
                for path in files:
                    if not path.startswith("tests/fixtures/"):
                        continue  # code files in a multi commit: handled by kinds
                    rel = path[len("tests/fixtures/"):]
                    if rel not in FIXTURE_MAP:
                        unmapped = True
                        continue
                    for tid in FIXTURE_MAP[rel]:
                        if "::" in tid:
                            if tid in i2n:
                                nums.add(i2n[tid])
                        else:  # test file entry: all its tests
                            for t in meta:
                                if t["file"] == tid:
                                    nums.add(t["number"])
                # unmapped fixture: fall back to everything (recall-safe)
                if unmapped:
                    nums = set(all_nums)
                workers = split_optimal(nums, sec) if nums else []
            else:
                workers = split_optimal(all_nums, sec)
        except Exception:
            traceback.print_exc()
            workers = split_optimal(all_nums, sec)
        lines.append({"commit": pf.stem, "workers": workers})
    return lines


def split_optimal(nums, sec):
    items = sorted(set(nums), key=lambda n: sec.get(n, 0), reverse=True)
    if not items:
        return []
    best = None
    for k in range(1, min(MAX_WORKERS, len(items)) + 1):
        loads = [0.0] * k
        for n in items:
            i = loads.index(min(loads))
            loads[i] += sec.get(n, 0)
        cost = max(loads) + WORKER_COST * k
        if best is None or cost < best[0]:
            best = (cost, k)
    k = best[1]
    workers = [[] for _ in range(k)]
    loads = [0.0] * k
    for n in items:
        i = loads.index(min(loads))
        workers[i].append(n)
        loads[i] += sec.get(n, 0)
    return workers


def main() -> None:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA
    for line in select(data):
        print(json.dumps(line))


if __name__ == "__main__":
    main()
