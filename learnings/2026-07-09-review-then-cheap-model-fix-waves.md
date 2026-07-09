# Reviewing another model's build, then fixing it with cheap subagents

**Problem (one line):** A freshly built codebase (by another model) needed a full correctness review, then all 10 findings fixed to "no bugs, no dead code" — using the cheapest model capable of each fix, with a stronger model only reviewing.

## Approach (plain steps)
1. **Review against the plan, not just the code.** Read the implementation plan first, then every source file. The biggest bugs weren't in any single function — they were *plan-vs-runner divergences*: fully-tested expansion machinery (`expand_corridor`/`expand_deadline`) that the runner never called, and config knobs (`alert_threshold`, `median_bucket`) that no code read. Grep every config key and every public function for callers; "tested but never called from production" is the signature of this failure mode.
2. **Verify each finding from the code before reporting it** (quote the line, construct the failure input). Ten findings survived; none were speculative.
3. **Partition fixes into file-disjoint batches** so agents can't collide: (A) runner semantics + its tests, (B) alerts/dashboard + their tests, (C) mechanical text edits (config/workflows/HTML). Assign models by task shape: haiku for mechanical text edits with exact before/after strings, sonnet for anything touching semantics or tests.
4. **Parallel agents must not run the full test suite** — another agent's half-written file makes it flaky. Each agent runs only the test files it owns; the reviewer runs the full suite after all waves land. Sequence any batch that touches files a previous batch changed (wave 2 extended wave 1's runner).
5. **Write agent prompts as specs, not tickets:** name the exact files allowed, the exact new behavior, the exact test scenarios with expected values computed from the fixtures (e.g. "fixture pairs are Fri→Mon 612/705, so threshold 600 → no alert, deadline 650 → alert"). Pre-computing expected values catches the agent's misreadings immediately.
6. **Reviewer re-reads every diff after the waves** — this caught an interaction regression no single agent could see: batch B's "latest observation day" dashboard filter was global, and batch C's new `--corridors-only` run would blank the inspiration table until the next discovery run. Fix: correlate each `MAX(ts)` subquery to the outer query's own predicate (route / source).
7. **Finish with an end-to-end smoke** (fixture-backed CLI run to a scratch DB) plus a dead-symbol grep sweep; one truly dead function (`trailing_median`) only showed up in the sweep, not in any diff.

## Judgment calls (deliberately NOT done)
- **Did not implement `median_bucket: route_month`** — it needs a daily_min schema change; removed the knob instead. A silently-ignored setting is worse than an absent one.
- **Did not delete the gated Phase-2 machinery** (spend guardrail, Duffel stub, seats.aero stub, SearchSpec's Tier-2 fields): it's tested, documented in the plan, and safety-critical. "No dead code" means no *unintentional* orphans, not stripping planned interfaces.
- **Did not git-commit** — the user never asked; repo left uncommitted as found.

## Reusable rule
When reviewing a generated build, hunt where the plan's machinery meets the orchestrator: grep every config key and helper for production callers — "built and tested but never wired in" is the dominant defect class. And when fanning fixes out to parallel agents, give each a disjoint file set and scoped tests, then re-review the *combined* diff yourself: the worst bugs live in the interactions between two individually-correct fixes.
