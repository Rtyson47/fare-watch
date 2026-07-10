# Duffel Tier 2: real paid verification behind a safety gate

## Problem
Add a real (billed) Duffel client and wire it into the Tier 1→Tier 2 runner,
without ever letting a test or an accidental config state make a live network
call that costs money.

## Approach
1. Read the existing gate first (`DuffelClient.enabled`, `DuffelGateError`,
   `spend.guard`/`record_duffel_search`) before writing anything — the safety
   contract already existed as a stub; the job was to fill it in, not redesign it.
2. Added the network primitive (`http.post_json`) mirroring the existing
   `get_json` shape — same injectable `opener`/timeout signature — so nothing
   new had to be learned by callers or tests.
3. Implemented `DuffelClient.search` behind the *same* `enabled` check that
   already existed; the only new code path is what happens once `enabled` is
   true, and that path never runs in a test unless a fake `post_json` is injected.
4. Built a *verify queue* during Tier 1 (a list of dicts) instead of re-walking
   corridor/deadline-watch specs in Tier 2 — this is the load-bearing decision:
   the original plan said "verify all corridor specs," which was rejected in
   the task brief itself for blowing the 100/day cap. Reusing the Tier-1
   `cheapest` fare already computed per corridor/watch keeps Tier 2 to ~10-15
   searches/run by construction, not by an added counter/limit.
5. Added a small pure function (`_duffel_mode`) to resolve live/test/off from
   env+config, tested in isolation — mode resolution is exactly the kind of
   logic that's easy to get backwards (e.g. `dry_run` accidentally allowing
   live), so it's separated from the loop and unit-tested directly rather than
   only through an end-to-end run.
6. In the loop: `spend.guard` before every live search, `try/except
   (OSError, ValueError)` around every search (mirrors the existing Tier-1
   `_fetch` error-swallowing pattern), and `handle()` (real alert) only in
   live mode — test mode only logs, never alerts, because sandbox prices are
   fictional and an alert on a fake price is worse than no alert.

## Judgment calls (deliberately not done)
- Did not re-verify raw corridor spec expansions (could be ~780 specs/corridor
  per the brief) — only the single cheapest fare already surfaced per
  corridor/watch, plus top-N inspiration candidates. This is the whole reason
  Tier 2 stays cheap; expanding it later requires deliberately widening scope,
  not just removing a guard.
- Did not let `duffel_client` injection bypass mode resolution — an injected
  client is only *used* if `_duffel_mode` already said "test" or "live"; this
  stops a test from accidentally proving a live path works when the mode
  resolver itself is broken.
- Test-mode alert assertions compare against a *separately computed tier1-only
  baseline run* rather than a naive before/after count, because Tier 1 alerts
  fire in a full run regardless of Duffel — comparing raw counts before/after
  the full run would have hidden a real Tier 2 alert bug.

## Reusable rule
When adding a paid/live capability behind an existing gate, extend the gate's
*existing* enabled-check and error-swallowing conventions rather than
introducing new ones — and make the "how much do we call this" decision a
structural one (reuse a value already computed) rather than a runtime counter,
so cost bounds hold even if someone forgets to check a limit later.
