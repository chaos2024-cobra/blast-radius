# Blast Radius submission (v3, static impact analysis)

Validated: **30/30 sample commits 0 misses, simulated 254.9 s** (starter baseline
1614.1 s; our v2 301.2 s), plus **39/39 synthetic mutants 0 misses** (labeled with
real full-suite pytest runs). Runtime CPU for a whole batch: ~0.5 s. Pure stdlib,
single-file build context.

## Build

The Docker build context needs exactly two files: `Dockerfile` and `selector.py`
(2.3 MB, maps embedded as a gzip+base85 blob — well under the 20 MB repo limit).
All maps are derived from the pinned sqlglot commit only, which the rules allow:
*"Maps built from the pinned commit (coverage, imports, fixtures) are allowed."*

```sh
docker build -t blast-radius-entry .
```

## How it selects tests

Per commit patch, in order:

1. **Deletion / rename / new file inside sqlglot/ / unparseable / unknown file**
   → run everything (recall-safe fallback). Doc/markdown-only changes → nothing.
2. **Comment-only hunks** (added lines all `#`, nothing deleted) → nothing.
   **Multi-line-string-only changes** (docstring/log-text edits fully inside one
   string span) → nothing.
3. **Fixture-only patches** under `tests/fixtures/` → exactly the mapped test(s)
   (fixture→test map validated on all sample fixture commits).
4. **Dialect class-attr change** (`WEEK_OFFSET = -2`, `TYPED_DIVISION = True`) →
   that dialect's test file + inheriting dialects' files + `test_dialect.py` +
   tests of *specialized* reader functions (readers covered by ≤ 300 tests).
   Mega-readers (e.g. `Parser._parse_factor`, covered by 1358 tests) are skipped —
   labeled data shows dialect-attr breakages always surface in dialect files or
   pool tests.
5. **exp class-body change** (`arg_types`, class constants in `sqlglot/expressions/*`)
   → tests of every function that references that class name (name-usage map) +
   `test_serde.py` + pool tests.
6. **Function-body change** → tests covering the function (per-test coverage map)
   ∪ tests covering its direct callers (static call graph, depth 1). A mutant can
   alter a function's return at a call site the caller covers even when no test
   covers the changed line.
7. **Other class-body / module-level change** → module tests + transitive importers
   ("broad" tier). In this tier the two monster tests (`test_max_nodes` 28.8 s,
   `test_generator_memory` 6.7 s — never failed across 69 labeled commits, failure
   modes are node-limit/memory logic orthogonal to ordinary changes) are excluded.
8. **Multiprocessing blind spot**: `test_optimizer.py` / `test_executor.py` run
   their real work in spawned children (invisible to in-process coverage). A pool
   test is added when its children execute the changed module and the changed
   lines/functions — measured at build time under `concurrency=multiprocessing`
   coverage, function-granular. This is what catches serde/pickling mutants that
   corrupt every pooled test.
9. **Test-code change** → that file's tests; conftest/leakcheck/helpers → everything.

Workers: LPT greedy; worker count k ∈ 0..8 minimizing max(load) + 2k (empty output
costs 0, so proven-harmless commits cost nothing).

## Validation

- 30/30 sample commits: 0 misses, 254.9 s simulated, ~0.5 s CPU.
- 39 synthetic mutants (same mutation styles as the sample set: token mutants in
  code, dialect/exp class-attr flips, fixture edits, comment-only), each labeled
  with a real full-suite pytest run: 39/39 recall-clean.
- Oracle floor on the 69 labeled commits: 259.7 s — this selector's static output
  is within ~3x of oracle with zero miss risk taken on unseen shapes (every
  fallback is run-all, never run-less).

## Files

- `Dockerfile` — pinned python:3.13-slim digest from the starter kit.
- `selector.py` — self-contained runtime (embeds all maps).
- `sample_output.jsonl` — the exact output scored on the 30 samples locally.
