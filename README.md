# Blast Radius submission (v1.1, conservative, single-file)

Validated on the 30 sample commits: **Simulated 648.2 s, 0 misses** (starter
baseline: 1614.1 s). Pure-stdlib Python; runtime CPU is well under a second.

## Build

The Docker build context needs exactly two files: `Dockerfile` and `selector.py`.
The fixture→test map is embedded inside `selector.py` (compressed base85 blob),
so there is no `maps/` directory to lose when copying the repo.

```sh
docker build -t blast-radius-entry .
```

## Strategy
1. **Comment-only patches** in `sqlglot/` (added lines are all comments/blank, no
   deletions) → run nothing (`workers: []`). On the sample set all 3 such commits
   break nothing.
2. **Fixture-only patches** under `tests/fixtures/` → run exactly the test(s)
   mapped to that fixture (map derived from the pinned sqlglot commit only —
   allowed under "maps built from the pinned commit"; validated 11/11 against the
   sample answers). Unmapped fixture → safe fallback: run everything.
3. **Everything else** (code changes, test-code changes, mixed, unparseable) →
   run all tests, split across up to 8 workers by LPT with worker count k chosen
   to minimize `max(load) + 2k`. This is recall-safe: cannot miss.

## Files
- `Dockerfile` — pinned python:3.13-slim digest from the starter kit, `COPY
  selector.py`, `CMD python /app/selector.py`.
- `selector.py` — self-contained runtime program (reads /data/tests.json and
  /data/commits/*.patch, prints one JSON line per commit to stdout).
- `sample_output.jsonl` — the exact output scored locally on the 30 sample
  commits (648.179 s simulated, 0 misses); not needed for the build.

## How the embedded map was made
Scanning the sqlglot checkout at commit eb11aec4be8cb2122afe713a4816662c3f0fb2fa:
optimizer fixtures map through `check_file("<name>", ...)` / `f"optimizer/{name}
.sql"` call sites in `tests/test_optimizer.py`; tpc-ds/tpc-h csv fixtures map to
the executor tests; other fixtures map to the test files that reference their
names. Then compressed with zlib and embedded as base85 in `selector.py`.

## Known headroom (not in v1.1)
- 9/16 sample "code" commits break nothing yet still trigger run-all (~56 s each).
  A static impact analysis (module import graph + changed-symbol tables + coverage
  map built at Docker-build time) could cut those to a few seconds each. That work
  is saved in `download/research/` (see NOTES.md) for a follow-up session.
