# Blast Radius — v4 selector (statement-granular static impact analysis)

## Results

| validation set | recall | simulated cost |
| --- | --- | --- |
| 30 sample commits | 30/30 (0 misses) | 244.9 s (starter: 1614.1 s, v2: 301.2 s, v3: 254.9 s) |
| 39 adversarial mutants (batch 1) | 39/39 | — |
| 27 adversarial mutants (batch 2: parser/generator core, tokenizer, helpers, optimizer rules, dialect attr flips, expression methods) | 27/27 | — |
| **all 96 combined** | **96/96** | **13.0 s/commit avg** |

Runtime CPU: ~0.0–0.2 s for a whole batch (pure static analysis, no test execution).

## How it works

For every commit the selector parses the unified diff and classifies each hunk:

1. **Comment-only / string-literal-only hunks** (docstrings, multi-line strings):
   no tests. Safe because string *contents* never change behavior, only error
   messages / doc text.
2. **Fixture files** (`tests/fixtures/**`): a precomputed fixture→test map
   (every fixture file in the pinned tree is loaded by exactly one known test).
3. **Test code**: that test file's tests. Helpers/conftest changes: everything.
4. **`sqlglot/` function changes — statement granularity.** This is the core
   improvement over v3. A mutated operand (`and`→`or`, `==`→`!=`, `is`→`is not`,
   `+`→`-`, constant tweaks) changes the evaluation of the *whole statement*
   containing it (short-circuit conditions, chained calls). So the at-risk test
   set is built from the statement's line span, not the single changed line:
   - tests executing any line of the mutated statement (coverage maps folded
     per statement at build time);
   - **callers, hybrid-granular**: tests of direct static callers, or — when
     that set is huge (hot callers like `can_quote`: 1153 tests) — the tests
     executing the callers' *call sites*, whichever set is smaller
     (2haz: 1153→102 tests);
   - **pool tests** (`test_optimizer`/`test_executor` run work in spawned
     children invisible to in-process coverage): children that execute any line
     of the mutated statement. Statement granularity fixed both directions:
     rszg's `and`→`or` on a never-executed line was missed by line granularity
     (condition short-circuit), while func granularity pulled all 25 pool tests
     for hot functions (5y72: 46→3 tests);
   - statement never executed in-process: the function's own tests + pool
     children executing the function.
5. **Dialect class-attr changes** (`WEEK_OFFSET = -1` etc.): dialect test files
   (own + all inheritors + `test_dialect.py`) + **all** reader functions' tests
   (uncapped — v3's ≤300 cap was a recall risk) + pool children executing readers.
6. **Expression class-body changes**: tests of functions referencing that class +
   `test_serde.py` + the module's own tests + pool children executing the users.
7. **Other class-body / module-level**: module tests + transitive importers.
8. **Unknown shape / rename / deletion / unparseable**: everything (recall first).

Workers: LPT greedy split, k ∈ 1..8 minimizing max(load) + 2k; empty output
costs 0 (no workers printed).

## Why static (no runtime verification)?

We built a fast verifier (unittest harness, ~0.3 s startup vs pytest's ~1 s) and
measured: verification spends CPU ≈ 1.15× the candidate set's test-seconds to
save at most ~1× simulated seconds — a net loss under the board's 1:1 CPU
charging. Static selection with tight, sound sets wins. (Details in the team's
research notes; the verifier code stays in `scripts/fast_verifier.py` for
reference.)

## Maps

Everything is precomputed from the pinned sqlglot commit (explicitly allowed:
"Tests are scored on their real runtime against the pinned commit"), compacted
to 3.2 MB (statement-RLE line coverage, index-encoded test sets, RLE pool child
lines) and embedded as gzip+base85 inside `selector.py`. Pure stdlib runtime.
