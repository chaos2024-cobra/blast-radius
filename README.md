# Blast Radius selector v7 — union engine

One file, pure stdlib. `select(patch) = V3Engine.select(patch) | V6Engine.select(patch)`,
each engine running on its own embedded maps (gzip+base85 blob).

## Why a union (board evidence)

| submission | hidden simulated | misses | total |
| --- | --- | --- | --- |
| v3 | 1023.5 s | 2 | **1624.3** |
| v4 | ~890 s | 3 | 1792 |
| v5 | ~405 s | 5 | 1907 |
| v6 (untested on board) | ~est. 950–1000 s | ≤ v4's 3 | est. 1850–1950 |

Every recall cut made the board score worse: the 300 s miss penalty is ~8×
the cost of even a run-all commit (36.8 s). v3's "wasteful" width was
catching hidden failures that the leaner versions dropped.

v7's selection is a **superset of both the v3 and v6 submissions on every
input by construction** (verified exactly on all 120 labeled commits), so
hidden misses(v7) ≤ min(misses(v3), misses(v6)) = 2.

## What the union fixes over v3 alone

- **v3's monster subtraction**: v3 removes its 2 "monster" tests (incl. the
  28.8 s `test_max_nodes`) from every broad selection; the v6 side never
  subtracts them, so the union keeps them.
- **v3's 300-cap on attribute readers** and depth-1 caller closure: the v6
  side adds uncapped readers, full callers, and callsite tests.
- **v6's keyword tier** (2350 keywords → tests whose source/fixtures mention
  the changed strings) unions into v3's width.
- v6's v3-wide function tier (statement ∪ function ∪ callers ∪ callsite ∪
  pool children) is itself ≥ v4's function tier.

## What v7 keeps from each engine

- v3 engine: importers closure on module-level hunks, dialect
  class-attr/class-body rules, expressions class-body rule, fixture map,
  deletion/unknown → run-all.
- v6 engine: no truncation anywhere (v5's caps removed), keyword tier,
  uncapped module+importers, min(func, callsite) callers, same
  fixture/deletion/unknown safety.

## Validation (real full-suite pytest labels + official kit scorer)

| set | commits | misses | simulated |
| --- | --- | --- | --- |
| kit sample (official scorer) | 30 | 0 | 303.5 s |
| adversarial synthetic mutants | 44 | 0 | 629.1 s |
| real post-pinned commits, code-only (official scorer) | 46 | 0 | 1036.8 s |

Superset checks: v7 ⊇ v3 on 120/120, v7 ⊇ v6 on 120/120. Runtime ~2 s per
46-commit batch (both engines), stdout 175 KB < 2 MB limit, single 5.9 MB
file < 20 MB repo limit.

## Expected board

Hidden simulated ≈ v3's 1023.5 s + 10–15% union overhead ≈ 1130–1180 s.
Misses ≤ 2 guaranteed (≤ v3), likely 0–2: every v3-specific hole found in
audit (monsters, attr cap, shallow callers) is covered by the v6 side.
Estimated total ≈ **1140–1790**, i.e. at worst around v3/v4's score, at best
~1400 better than the current v5 board result.

## Maps (derived only from the pinned sqlglot commit — allowed)

Both engines use maps built from the pinned commit: per-test coverage
(module/function/statement → tests), AST symbols, importers, dialect map,
attr readers, name usage, docspans, callsites, callgraph, fixtures, keywords,
pool (spawned-process) coverage. No hidden-set information is used.

## Run

```
docker build -t blast-radius-v7 .
docker run --rm -v /data:/data blast-radius-v7     # one JSON line per commit
```

Locally: `python selector.py <dir with tests.json and commits/>`.
