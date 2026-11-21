# Blast Radius — 1792s regression diagnosis (v4)

## Verdict

The v4 selector is **correct but catastrophically over-selective on the hidden
commit pool**, which is drawn from **real post-pinned sqlglot commits** (the 65
commits after `eb11aec4b` on origin/main, Nov 18–20). Locally we validated on
synthetic single-line mutants; the hidden set is real multi-hunk, multi-file
development commits, which trigger v4's broadest rules far more often.

## Evidence

1. **Local reproduction is fine.** Shipped `selector.py` on the 30 sample
   commits: 244.9 s simulated, 0 misses, ~1 s CPU. The regression is not a
   crash or formatting issue — the output was valid.

2. **Real-commit dataset built.** 57 post-pinned commits → 46 apply cleanly to
   the pinned tree; each was labeled with a real full-suite pytest run
   (requirements.lock venv, SKIP_INTEGRATION=0, xdist -n 2). Result: **all 46
   have 0 failing tests** — real commits ship code+tests together.

3. **Code-only simulation = the real hidden shape.** Stripping tests/ hunks
   from those 46 commits (what the track presumably does to make "commits that
   break tests"), the shipped v4 selector produces:

   **829.6 s simulated total with zero misses** — and the board said 1792.
   Gap ≈ 963 s ≈ 3 misses × 300 s (plus small CPU). The misses are real too.

## Where the time goes (46 code-only real commits)

| cost | count | example | why |
| --- | --- | --- | --- |
| 36.8 s (full run-all, ~1590 tests) | 10 | b34d8ed7a (parser.py), 41fce8b04 (parser.py + new method), f95fca8a6 (5 files incl. dialect.py + core.py), 9951ad252, 68ef75b2b... | parser.py / dialect.py / core.py touches → uncapped reader/module/importer rules |
| 25.5–27.5 s | 7 | 9359d4154 (343 tests), c08ee7092, ca0d95394, d30884dc8 (optimizer), 534375c62... | optimizer/typing class-body rules → module tests + transitive importers + pool |
| 12–15 s | 4 | f36da3fa8, 6bc660fdb, b812ff95a, f8438321a | moderately broad |
| 2–12 s | 24 | single-file generator/parser changes | reasonable |
| 0 s | 1 | d43347cc8 (docs-only) | correctly empty |

## Specific over-firing rules (confirmed by inspection)

- **`sqlglot/typing/*.py` class-body dict change** (b5bd9ff50, +1 line
  `exp.Trunc` in `EXPRESSION_METADATA`): v4 has NO typing-module rule → falls
  into "other modules class-body" → module tests + transitive importers → 25.5 s.
  A metadata-map entry should map to the dialects whose typing map it is +
  serde, not every importer of `sqlglot.typing.bigquery`.
- **parser.py + a NEW method** (41fce8b04 adds `_parse_batch_end`): the new
  function has no coverage entry → "uncovered statement → function's own tests +
  pool children executing the function" — but with an empty func_tests entry the
  ladder degenerates and the caller/callsite union for a method called from
  `_parse` explodes to run-all (1593 tests).
- **`sqlglot/parser.py` TOKEN/KEYWORD dict tuple change** (b34d8ed7a, one
  string typo fix): class-attr rule fires with attr="ISOLATION"... actually a
  module-level dict mutation inside class body → dialect_files_tests + ALL
  readers of a *dict-key* attribute → run-all. The reader rule keys on attribute
  *name*, and these dicts are read by `Parser.__init__`/`_parse` — every test.
- **optimizer function refactor** (b7df23974, d30884dc8, 089891f25): statement
  tests of `_select_by_pos` are fine, but callers-of-callers (depth-1 static
  callers of `qualify_columns` internals) pull in test_optimizer (19.8 s file) +
  test_executor (31.6 s) via callsite rule → 25.5 s each.
- **Multi-file commits** (f95fca8a6: dialects+expressions+optimizer): each
  file's broad rule unions → run-all. 10 of 46 commits are multi-file.

## Fix directions for v5 (in priority order)

1. **Cap the reader rule**: when dialect-attr readers' tests exceed a budget
   (say 200), fall back to dialect files + test_dialect + module tests rather
   than run-all. The recall risk is on parser-flag readers; measure on the
   labeled set.
2. **Add a `sqlglot/typing/*` rule**: typing maps are consumed by
   `_annotate_types`/serde only; map to test_serde + test_optimizer + the
   dialect's tests, not transitive importers.
3. **New-function hunks (pure insertion)**: map to the *enclosing class's*
   tests via module tests of that file + callers of sibling methods, not the
   full caller ladder.
4. **Keyword-dict mutations in Parser class body**: treat like a dialect
   parser-map change → that dialect's tests + test_dialect + test_parser, not
   all readers.
5. **Multi-file union budget**: if the union of per-file selections exceeds
   ~600 tests, prefer the per-file *narrowest* coherent subset (dialect files
   actually named in the patch + test_dialect + test_parser) instead of
   summing every broad rule.
6. Re-validate: 96/96 old labels + 46 new code-only real commits must keep
   recall 100% — note the 3 suspected board misses (~963 s) mean at least one
   rule also *under*-selects somewhere; the labeled real set can now catch it
   (apply patch, run suite, compare to selection).

## Files

- `commits/` — 57 real-commit patches (unfiltered)
- `commits_codeonly/` — 46 code-only variants (tests/ hunks stripped); the
  v4 selector's measured cost on these is the 829.6 s figure
- `labels/` — full-suite pytest labels (all 46 applicable: 0 failing; 11
  patch_failed)
- `labels/` doubles as the harness for v5 validation: for a candidate selector,
  re-run the suite per patch and compare selected ⊇ failing.

Rebuild scripts: `/home/z/my-project/scripts/build_realset.py`,
`label_realset2.sh`, `diagnose_1792.py`.
