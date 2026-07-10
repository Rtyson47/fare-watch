# Smoke-test with the user's real config, not just fixtures

**Problem (one line):** After three agents shipped individually-correct changes (multi-origin labels, Duffel Tier 2, dashboard options), the remaining bugs were invisible to the 90+ green unit tests — they only appeared when running the tool against the user's actual config.yaml.

## Approach (plain steps)
1. After every fix wave, run the real CLI end-to-end (`FAREWATCH_FAKE_TP=1 monitor.py run --dry-run` with scratch --db/--data paths) against the **repo's live config**, not the sanitized example the tests use — then eyeball every row of the exported data.json against what the config promises.
2. That eyeball caught two bugs the suite couldn't: (a) two corridors sharing origin/dest ("YVR-LON one-way" and "YVR-LON return") surfaced each other's fares as "current cheapest" because fare queries key on origin/dest while histories key on labels; (b) once Duffel test mode is enabled, synthetic sandbox prices would enter the same fare queries and display as real cheapest prices.
3. Both fixes were filters at the query layer: a trip-shape clause (`return_date IS NULL / IS NOT NULL`) derived from each corridor's `trip_type`, and a `source != 'duffel_test'` exclusion. Rule of thumb: when a table mixes rows from watches that share natural keys, every read query needs a discriminator for each axis the writers vary on (trip shape, data source), not just the natural key.
4. Keep the fake client faithful to the API contract: FixtureTP ignored the `one_way` request parameter, so fake-mode data couldn't even represent the distinction — fixing the double (honor `one_way`, strip return dates) let the smoke test exercise the real semantics.

## Judgment calls
- Fixed these inline as the reviewer (a dozen lines) instead of dispatching another agent — the subagent pattern pays for itself on batches, not two-line SQL filters.
- Deadline-watch queries got `one_way=True` hard-coded (they are one-way by construction) even though it briefly broke fixture-based tests — fixed the fixtures to match reality rather than loosening the filter.

## Reusable rule
Unit tests validate each change against its own spec; only an end-to-end run against the *user's real configuration* validates the changes against each other. After parallel/staged agent work, always smoke the real config and diff the actual output against what the config promises, row by row.
