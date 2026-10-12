# Changelog

## v0.1.1 (2026-10-13)

Round-2 revision after full self-review of the v0.1.0 draft:

- Added 4 extreme-edge test cases (tiny float budgets, 200-level deep chain,
  p99 at 80% of budget staying clean, duplicate attribution records);
  suite grew 64 -> 68 cases, all PASS.
- Fixed self-test index mapping for attribution fixtures (breach / unknown
  component / near-limit / clean rows now feed the right measurements) and
  corrected the deep-exceed message assertion to the node that actually
  breaches; removed a dead mapping constant.
- Measured and documented Performance numbers ([Measured] tags, repro
  commands).
- Added ALIGNMENT.md (rules 85-100 audit, 16 items with evidence).

## v0.1.0 (2026-10-13)

Initial draft:

- Budget tree validation: positive numeric budget_ms (bool/string rejected),
  layer whitelist {gateway, service, db, cache, external}, unique node
  names, children-not-list handling, children-sum <= parent rule with
  BUDGET_EXCEEDED errors and HEADROOM_LOW warnings above 90% utilization.
- Attribution audit: component existence, positive p50/p99, BUDGET_BREACH
  errors, NEAR_LIMIT warnings, UNMEASURED warnings for measured:true nodes.
- CLI (`check`, `--attribution`, `--json`) with exit-code contract 0/1/2.
- Self-test suite: 64 cases across functional / exception / extreme-edge
  classes, `SUMMARY: PASS n/n` reporting, four-defence template.
- README, MIT LICENSE.
