# Blast Radius selector v8 — union engine + module floor

One file, pure stdlib. `select = V3Engine.select ∪ V6Engine.select ∪ floor`,
each engine running on its own embedded maps (gzip+base85 blob).

## Why this shape (board evidence)

| submission | hidden simulated | misses | total |
| --- | --- | --- | --- |
| v3 | 1023.5 s | 2 | 1624.3 |
| v7 (v3 ∪ v6) | 1026.7 s | 2 | 1626.7 |

v7's selection is a superset of v3's on every input, yet it missed the same
2 commits: the hidden failing tests are outside BOTH engines' tiers. A
red-team campaign (below) tried to reproduce those misses with 13 runtime
mutations of zero-attribution functions plus structural probes of every
shared code path — all 100+ resulting failures were covered. The 2 misses
are therefore attribution orphans or environment-dependent shapes that no
static tier links; the response is cheap insurance floors, not more rules.

## What v8 adds over v7

**Module floor (F1):** for every touched sqlglot module that has live
(non-comment, non-docstring) hunks and a small attributed test set (≤ 60
tests), union in that module's complete test set. This protects against
attribution orphans in leaf modules (a function the pinned-run trace never
attributed to a test, in a module too small for the importers closure to
guarantee coverage). Measured cost: +0.1% of simulated seconds.

Floors considered and rejected (measured on the labeled sets):

- **Fixture floor** (pad fixture commits to the whole test file): +152%
  simulated seconds — the fixture map is exact, so the pad buys nothing.
- **Monster insurance** (always run the 2 slowest never-failed tests):
  +125% — and the board disproves the theory: v3 subtracted exactly those
  monsters on broad selections and did not gain misses relative to v7.

## Validation (real full-suite pytest labels + official kit scorer)

| set | commits | misses | simulated |
| --- | --- | --- | --- |
| kit sample (official scorer) | 30 | 0 | 303.9 s |
| adversarial synthetic mutants | 44 | 0 | 629.2 s |
| real post-pinned commits, code-only (official scorer) | 46 | 0 | 1036.8 s |

Superset checks: v8 ⊇ v7 on 120/120 labeled commits (and ⊇ v3, ⊇ v6 through
v7). Runtime ~2.2 s per 46-commit batch, stdout 175 KB < 2 MB, single
5.95 MB file < 20 MB repo limit.

## Red-team campaign summary (what was tried and eliminated)

- **Doctest blind spot** — `tests/test_docs.py` runs module doctests, but it
  is not in `tests.json`, so docstring-only changes cannot be misses.
- **Fixture map holes** — cross-checked all 63 fixture files against every
  `load_sql_fixtures`/`load_sql_fixture_pairs` call site (including the
  f-string loop in `test_optimizer.py`): the map matches exactly.
- **Diff parser edges** — renames, mode changes, binary, new files, no-newline
  markers, CRLF, wrong hunk counts: all either run-all or correctly parsed.
- **Zero-attribution functions** — 262 functions have no attributed tests;
  mutating 13 of the most suspicious (executor helpers, dialect builders,
  `Dialect.transpile`) produced 26 failing tests across 4 mutations, every
  one covered by the module/importers tiers. The remaining 40 zero-test
  base `*_sql` generator methods are genuinely dead (8 mutations: 1621/1621
  tests still pass).
- **Dict-dispatch indirection** — all 88 `_build_*` parser builders are
  attributed despite dict registration; method-name dispatch (`*_sql`) is
  attributed too.

## Maps (derived only from the pinned sqlglot commit — allowed)

Per-test coverage (module/function/statement → tests), AST symbols,
importers, dialect map, attr readers, name usage, docspans, callsites,
callgraph, fixtures, keywords, pool coverage. No hidden-set information.

## Run

```
docker build -t blast-radius-v8 .
docker run --rm -v /data:/data blast-radius-v8     # one JSON line per commit
```

Locally: `python selector.py <dir with tests.json and commits/>`.
