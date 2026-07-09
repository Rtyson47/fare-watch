# Building a two-tier fare monitor (free discovery → paid verification)

**Problem (one line):** Scaffold a personal flight-fare monitor where a *free, cached* API does open-ended discovery and a *paid, billed* API verifies only a tiny shortlist — without ever risking an accidental charge, and shippable Tier 1 first.

## Approach (plain steps)
1. **Ground the data shapes before writing code.** Fetched the real Travelpayouts API reference and confirmed the trap: v2 endpoints (`prices/latest`, `month-matrix`) use `value` for price + `depart_date` and return a **list**; v1 endpoints (`city-directions`, `prices/cheap`) use `price` + `departure_at` and return a **dict keyed by destination**. Recorded these as fixtures.
2. **Normalize everything to one shape.** A single `FareRecord` dataclass with two adapters (`from_tp_v2_row`, `from_tp_v1_entry`). Every downstream module (storage, alerts, dashboard) only ever sees `FareRecord` — the provider quirks die at the boundary.
3. **Make the network a single injectable seam.** All HTTP goes through one `get_json(url, params, opener=None)`. Tests pass a fake that records params and returns a fixture, so the entire suite runs offline with zero network.
4. **Build bottom-up with TDD, one module per task:** config → models → db → provider client → corridor/date expansion → inspiration filter → alerts → spend guardrail → notify → report/dashboard → runner/CLI. Each: write failing test, see it fail, implement, see it pass.
5. **Gate the paid tier in code, not just docs.** Duffel `search()` raises `DuffelGateError` unless a *double gate* is open (config `live_confirmed:true` AND env `DUFFEL_ENABLE_LIVE=1`), and even then the live call is a deliberate `NotImplementedError`. A test locks the gate shut.
6. **Prove it end-to-end** with a `FAREWATCH_FAKE_TP=1` switch (fixture-backed client) and verify the static dashboard actually renders in a browser preview (Chart.js loaded, tables populated, deep links well-formed).

## Judgment calls (what I deliberately did NOT do, and why)
- **No live Duffel/Telegram calls, no auto-commit.** The spec said "ask before Duffel charges"; billed/outward actions wait for explicit go-ahead. Built the guardrail + spend tracking now so Phase 2 is a wiring job.
- **stdlib `urllib` + `PyYAML` only, no `requests`/framework.** Solo tool, minimal deps, trivially runnable in CI.
- **Resolved spec ambiguities explicitly in the plan** (median bucket = route over trailing 30d; `daily_min.date` = observation date; deep links *constructed* since the cached API rarely returns one; `region_whitelist` matches country code or explicit IATA) rather than guessing silently — documented each so they're not re-litigated.
- **Skipped the secondary `prices/cheap` endpoint and seats.aero live impl** (YAGNI / gated) — stubbed with TODOs.

## Reusable rule
When integrating multiple providers of the same concept, **normalize to one internal shape at the boundary and route all I/O through a single injectable function** — then business logic is provider-agnostic and 100% testable offline against recorded fixtures. And **when one path costs money, gate it in code with a test that proves it's shut**, not just a comment.
