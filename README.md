# latency-budget-spec

A stdlib-only validator for layered latency budgets: declares a budget tree (gateway -> service -> db/cache/external), checks children sums fit parent budgets with headroom warnings, and audits p99 attribution records against declared budgets. If you own an SLO that keeps getting blown by an unnamed layer, use this; otherwise skip it.

## Problem

"A target of 300 ms" means nothing until someone asks: how much does the gateway get, how much the service, how much the database? Budgets declared only at the top silently oversubscribe — children sum to 120% of the parent — and when p99 regresses, nobody can say which layer spent the money. Teams need a checked-in, mechanical budget contract.

## How it works

- Budget tree = JSON: node = `{name, layer, budget_ms, children: [...]}`; layers in {gateway, service, db, cache, external}.
- Validation: positive numeric `budget_ms` (bools rejected), non-empty unique names, valid layers; per node, children budgets must sum within the parent (ERROR `BUDGET_EXCEEDED`) and warn above 90% utilization (`HEADROOM_LOW`).
- Attribution audit: records `{component, p50_ms, p99_ms}` are checked against the tree — unknown components are errors, p99 above budget is `BUDGET_BREACH` (ERROR), p99 within 10% of budget is `NEAR_LIMIT` (WARN), and nodes marked `measured: true` without a record get `UNMEASURED` (WARN).
- Findings are `{code, severity, message, location}`; exit 1 on any ERROR.

## Quickstart (~2 min)

```bash
python latency_budget_spec.py check budget.json                          # ~0.5s
python latency_budget_spec.py check budget.json --attribution p99s.json  # audit measurements
python latency_budget_spec.py check budget.json --json                   # CI-friendly output
```

Then run the self-test suite: `python self_test.py` (~0.5s).

## Why not X

No direct equivalent found as of 2026-10-13: searches for "latency budget tree validator / latency budget allocation tool" surface SRE essays and observability features, not standalone offline validators. Nearest neighbors:

- **OpenTelemetry / tracing backends (Jaeger, Tempo)** — show *measured* latency breakdowns after the fact; none validate a *declared* hierarchical budget or its arithmetic.
- **SLO platforms (Nobl9, Sloth)** — manage SLO targets and error budgets at the service level; they don't model intra-request layer allocation.
- **JSON Schema + ajv** — field checks only; no parent/children sum semantics, no headroom logic, no attribution audit.
- **Custom spreadsheet** — the usual fallback; no CI gate, drifts immediately, no node-name uniqueness or unit enforcement.

## Performance

Measured on CPython 3.13.12, Windows 10 Pro, 2026-10-13:

- Full self-test suite (68 cases): **~0.5 s** [Measured] — repro: `python self_test.py`
- Validate a 500-node deep budget tree: **~33 ms/op** [Measured] — repro:

```bash
python -m timeit -s "import latency_budget_spec as m, json; t=json.load(open('budget.json'))" "m.validate_budget(t)"
```

Validation is a single recursive pass, O(nodes); attribution audit is O(records + nodes).

## Minimal Fallback

No installs needed beyond Python 3.8+. If you cannot run the validator, enforce the invariant in a spreadsheet column: `children_sum <= budget_ms` per row, and a one-line check for p99 vs budget. You lose uniqueness checks, headroom warnings, and the exit-code contract.

## Design Trade-offs

- **Sum-based composition over percentile math**: naive sums ignore that percentiles don't add. We chose the simpler, stricter contract (documented) because it is checkable without a statistics engine.
- **Headroom warning at 90%**: early signal without noise; the threshold is a constant, not configurable, to keep behavior reviewable.
- **Priority order**: budget arithmetic correctness > measurement coverage > convenience.

## Limits & Second-order Effects

- Sum-based budgets are conservative: real p99s don't add linearly, so a "passing" tree can still miss its top-level SLO.
- Parallel fan-out (children executing concurrently) makes child sums overstate latency; the model under-allocates for such designs — treat as a ceiling, not a floor.
- Widely adopted, teams may inflate layer budgets to game headroom warnings, or declare `measured: false` to silence UNMEASURED — the ledger records intent, not physics.

## FAQ

**Why sums instead of percentile addition math?** Percentile composition requires distribution assumptions; sums are assumption-free and fail loudly. Conservative by design.

**Can a node have zero children?** Yes — leaves are normal; the sum rule only applies when children exist.

**When NOT to use this tool?** Skip it if your stack already enforces per-layer deadlines in code (e.g., propagated context deadlines with automatic truncation) — a parallel declared tree will drift from reality. Also skip for single-service systems where one budget suffices.

## [Core Assumptions]

1. A request path can be modeled as a tree of named layers with additive millisecond budgets.
2. p99 is the operationally meaningful percentile for attribution.
3. Node names are stable identifiers worth de-duplicating across the tree.
4. Budgets live as reviewable JSON in git so changes get code review.

---

Confidence: High (≥80%) for tree/arithmetic/attribution behavior — 68 self-test cases including 200-level chains and 1000-node trees. Medium (60-79%) that sum-composition is acceptable overhead for most teams — depends on architecture (fan-out vs sequential). Data as of 2026-10-13.

---

Part of the [zhengming-toolbox](https://github.com/chenhz01/zhengming-toolbox) — 105 purpose-built AI-engineering tools across neglected niches.

Related tools: [free-tier-exhaustion-predictor](https://github.com/chenhz01/free-tier-exhaustion-predictor) · [token-price-table-validator](https://github.com/chenhz01/token-price-table-validator) · [oncall-handoff-spec](https://github.com/chenhz01/oncall-handoff-spec)
