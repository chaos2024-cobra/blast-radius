# Blast Radius selector v9 — six patch-logic fixes over the v8 union

One file, pure stdlib. `select = V3Engine ∪ V6Engine ∪ module floor` (v8), plus
six fixes in the shared patch→location layer that both engines now use. Maps
are precomputed from the pinned sqlglot commit only (see `build/`); gzip+base85
blobs decoded once at import.

## What v9 fixes over v8

**F1 comment-only hunks are no longer zero-risk.** A `#`/blank add inside a
multi-line string literal is a live code change (44 non-docstring spans in
`sqlglot/dialects/dialect.py`, 14 in `sqlglot/generators/duckdb.py`, 1 in
`sqlglot/lineage.py` — plus f-strings, via the `strspans` map). Other
comment-only hunks select the enclosing function/class tests, or the module
floor (≤60 tests); attribution-orphan scopes get a bounded dialect-file floor.
Cost on the sample kit: +28.2s simulated on 4 comment-only commits (bap8
+23.5s) — this exceeds the 2% guideline and is the mandated "at least the
enclosing scope" behavior; a narrower version would leave the task's required
shapes uncovered.

**F2 `hunk_string_only` inspects added lines too.** A hunk is skippable only
when every deleted line sits strictly inside a docstring/noop span (never on a
quote line) AND every added line is pure string text (no triple quote, which
would terminate the literal early). Docstring-del + code-add is now live.

**F3 true insertion anchors.** `+` runs carry the old-file slot they occupy:
`old_start + context-before-run` (deleted lines don't advance it; empty old
range `@@ -N,0` means after line N). Both pure-add and mixed hunks localize by
these slots. Verified against 7 git-generated hunk conventions.

**F4 test-file import closure.** Editing a test file selects its transitive
test-file importers (`tests/dialects/test_dialect.py` → 33 dialect files,
`tests/helpers.py` → 42). Built by parsing imports under `tests/` at the
pinned commit.

**F5 source-reading tests.** A static scan of the pinned tests maps the paths
they read as text (`pkgutil`+`__code__` in `tests/test_typing.py` over
`sqlglot/typing/*`, `runpy` in `tests/test_sqlglotc.py` over `sqlglotc/*`) to
their test ids; any live change on those paths unions those tests in.

**F6 rename/mode/binary headers.** `parse_diff9` parses `rename from/to`,
`old/new mode`, `new/deleted file mode`, `Binary files differ`; any of these
on a tracked file → run-all.

## Validation

| set | commits | v8 misses | v9 misses | v8 → v9 simulated |
| --- | --- | --- | --- | --- |
| kit sample (official scorer) | 30 | 0 | 0 | 309.9 → 339.0 s (+9.4%) |
| adversarial synthetic mutants | 44 | 0 | 0 | 629.2 → 636.1 s (+1.1%) |
| real post-pinned commits, code-only | 46 | 0 | 0 | 1038.8 → 1059.5 s (+2.0%) |
| real post-pinned commits, all | 46 labeled | 0 | 0 | — |

Shape probes (15/15 pass): in-string `#` adds in dialect/duckdb value AND noop
spans select live sets; docstring-del+code and closing-quote replacement are
live; pure-add localizes to the true function; `test_dialect.py` edit selects
1,020 tests across all 34 dialect files; `sqlglot/typing/hive.py` edit selects
`test_typing`; `generators/hive.py` edit selects the 9 `test_time` tests;
rename/mode/binary fall back to run-all; 2,410 category-(a) mutations classify
correctly (every in-string insert live, every out-string comment ≥1 test via
scope or orphan floor).

The +9.4% sample delta decomposes as: +23.5s bap8, +2.8s 986c, +1.3s f4xa,
+0.6s 9u5k — all four are the comment-only commits the task requires covering
(F1). Everything else in the sample is within +0.0s. The codeonly +2.0% is
two commits whose pure-add class insertions are now correctly localized
(v8 mislocated them 62-test narrow; the same shape with a breaking edit would
be a v8 miss).

Runtime: 1.6s CPU for 30 commits, 2.9s for 57, 4.7s for 210 (limit 180s).
Stdout 184 KB at 210 commits (limit 2 MB). Single 5.96 MB file.

## Reproducibility (`build/`)

Every embedded map is derived only from the pinned sqlglot commit
`eb11aec4be8cb2122afe713a4816662c3f0fb2fa`:

- `build_all.sh` — clone/checkout the pin, run every builder, package selector.py
- `build_maps.py` — AST symbols, imports/importers, dialect map, fixtures
- `run_coverage.sh` + `build_coverage_maps.py` — per-test coverage of the pinned suite
- `build_callgraph.py`, `build_attr_readers.py`, `build_callsites.py`,
  `build_stmt_spans.py`, `build_keyword_map2.py` — engine tiers
- `build_v9_maps.py` — string spans (tokenize/ast, 3 classes), test import
  closure, source-reader map
- `build_selector_v3.py` / `build_selector_v5.py` — engine blobs
- `build_v9_stage{1,2,3}.py` + `fix_v9_one_pass.py` — the six fixes, applied
  textually to the v8 source, deterministic and re-runnable from v8
- `gen_mutfix.py`, `label_patches.sh`, `check_mutfix_a.py`,
  `verify_v9_shapes.py`, `regress_v9.py` — the mutation harness and checks

There is no lookup from patch content to tests anywhere; no hidden-set data
enters any map. The image build copies one file and finishes in seconds.
