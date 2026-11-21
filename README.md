# Blast Radius submission (v2, impact-based)

Validated on the 30 sample commits: **Simulated 301.2 s, 0 misses** (starter
baseline: 1614.1 s; v1 conservative: 648.2 s). Pure-stdlib Python; the whole
batch runs in ~0.3 s of CPU.

## Build

The Docker build context needs exactly two files: `Dockerfile` and `selector.py`.
All analysis maps are embedded inside `selector.py` (gzip+base85 blob, 0.4 MB),
derived from the pinned sqlglot commit only — allowed under the rules: *"Maps
built from the pinned commit (coverage, imports, fixtures) are allowed."*

```sh
docker build -t blast-radius-entry .
```

## How it selects tests

For each commit's patch:

1. **Comment-only hunks** (added lines are all `#` comments, nothing deleted) →
   run nothing. Comments cannot change behavior.
2. **Fixture-only patches** under `tests/fixtures/` → exactly the test(s) that
   read that fixture (fixture→test map built from the pinned tree; validated
   11/11 on samples).
3. **Class-attribute change** (`NAME = value` on a class body, e.g.
   `WEEK_OFFSET = -2`) → tests covering functions that *read* that attribute
   (static reader map) + the owning dialect's test files + inheriting dialects'
   test files + `test_dialect.py`.
4. **Function-body change** → tests covering the changed function (per-test
   coverage map) ∪ tests covering its callers up to depth 3 (static call graph).
   A mutant inside a function can alter its return value at a call site the
   caller covers even when no test covers the changed line itself.
5. **Class-body / module-level change** → tests of the module + transitive
   importers (dialect modules: own + inheriting dialect test files instead).
6. **Multiprocessing blind spot**: `tests/test_optimizer.py` and
   `tests/test_executor.py` run their real work (parse/optimize/execute) in
   spawned child processes, invisible to in-process coverage. For any change in
   a module a pool child executes, those pool tests are added (per-test child
   module map, measured at build time under `concurrency=multiprocessing`
   coverage). This is what catches serde/pickling mutants (`__reduce__` →
   `serde.dump`) that break every pooled test.
7. **Test-code change** → that test file's tests; conftest/leakcheck/helpers →
   run everything.
8. **Anything unknown or unparseable** → run everything (recall-safe).

Worker split: LPT greedy, worker count k ∈ 1..8 minimizing max(load) + 2k.

## Validation

- 30/30 sample commits, 0 misses, 301.2 s simulated.
- Recall additionally validated on synthetic mutants (token-level mutants in the
  same styles as the sample set: code / class-attr / fixture / comment / multi),
  each labeled with a real full-suite pytest run — see the repo's research notes.
- Fallback safety: any exception during selection for a commit falls back to
  run-all for that commit; a missing/unmapped input at any step degrades to
  run-all rather than guessing small.

## Files

- `Dockerfile` — pinned python:3.13-slim digest from the starter kit.
- `selector.py` — self-contained runtime (embeds all maps).
- `sample_output.jsonl` — the exact output scored on the 30 samples locally.
