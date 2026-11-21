# Blast Radius selector v5

Statement-granular static impact analysis, self-contained (pure stdlib, maps
embedded as a gzip+base85 blob inside `selector.py`; build context = 1 file).

## Why v5 (v4 scored 1792 on the hidden practice set)

Post-mortem of the 1792: the shipped v4 selector was *valid* (244.9 s simulated,
0 misses on the 30 sample commits, ~1 s CPU) but **over-selected to run-all on
real commits**. The hidden pool is drawn from real post-pinned sqlglot commits
(multi-hunk, multi-file development changes), which trip v4's broadest rules
constantly. Measured on 46 real post-pinned commits with the test hunks stripped
(the hidden-set shape): v4 selected 829.6 s of tests with ~3 misses
(829.6 + 3×300 + CPU ≈ 1792).

## What changed in v5

1. **Keyword tier (new)**: class-body string-dict/tuple changes in core
   parser/generator/tokenizer modules map the *changed strings* (removed and
   added) to tests whose source or fixtures mention the keyword (token match or
   substring ≥ 4 chars). Example: the `TRANSACTION_CHARACTERISTICS` typo fix
   (`UNCOMITTED`→`UNCOMMITTED`) selects 40 tests (3.2 s) instead of 1592
   (36.8 s). Keyword map: 2350 keywords, median 3 tests per keyword.
2. **module+importers tier replaced**: module tests capped at 140 (+ importers
   while total ≤ 280); core modules (parser, generator, tokenizer_core, tokens,
   helper, transforms, errors, trie — whose module tests are ~run-all) get the
   keyword tier + bounded baseline files (test_dialect + test_transpile +
   test_expressions) instead.
3. **Caller rule capped**: callers with > 400 covering tests (`Parser._parse`,
   `Tokenizer.*`) contribute nothing extra (their coverage equals the callee's
   statement coverage, already selected); the caller union is capped at 200.
4. **Recall buckets restored to v3 width** (v4's narrowing likely caused the
   board misses): function tier = statement tests ∪ function tests ∪
   small-caller function tests ∪ callsite tests ∪ pool children (function-level
   or statement-line-level). The pool bucket matters: `test_optimizer` /
   `test_executor` run SQL in spawned children invisible to in-process coverage.
5. Dialect class-attr, expressions class-body, fixtures, test-code, deletion,
   rename, unknown-shape rules unchanged from v4 (recall-safe).

## Validation (all with real full-suite pytest labels)

| set | commits | misses | simulated |
| --- | --- | --- | --- |
| kit sample (official scorer) | 30 | 0 | 283.0 s (v4: 244.9) |
| adversarial synthetic mutants | 39 | 0 | 558.2 s |
| real post-pinned commits, code-only | 46 | 0 | 797.5 s (v4: 829.6 + ~3 misses) |

The +38 s on the sample set vs v4 is deliberate: the wider recall buckets
insurance against 300 s misses (v4's board run had ~3). CPU: ~1.1 s per batch.

Five commits remain at run-all (36.8 s each) for any recall-safe selector: a
change to a statement inside `Parser._parse` / `TokenizerCore.__init__` /
`_scan_*` is executed by ~1550 of 1620 tests, so every one of them can fail.
The remaining cost is dominated by two monster tests (test_max_nodes 28.8 s,
test_execute_tpcds 21.4 s) that appear in selections only when coverage maps
say they execute the changed code.

## Maps (derived only from the pinned sqlglot commit — allowed)

`test_ids`, `symbols` (AST spans), `importers`, `dialect_map`, `attr_readers`,
`name_usage`, `docspans`, `func_tests`/`module_tests`/`stmt_rle` (line/statement/
function/module → covering tests, from a real coverage run incl. spawned-pool
children), `callsite_tests`, `callgraph_edges`, `fixture_map`, `keywords`.

## Run

```
docker build -t blast-radius-v5 .
docker run --rm -v /data:/data blast-radius-v5     # prints one JSON line per commit
```

Locally: `python selector.py <dir with tests.json and commits/>`.
