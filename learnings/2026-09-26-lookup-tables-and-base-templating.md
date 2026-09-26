# Lookup tables behind filters, and what moves when a base moves

**Problem:** add London→Japan→Australia routes with a "fly on at least a month after landing" rule, move the Mexico/Canada routes out of the way on the dashboard, and switch the inspiration list from Mexico to "Europe returns from London, next month".

## Approach
1. Found the dashboard first. It wasn't in CC/ or in artifacts. A session-transcript search for "inspiration" pointed to `~/fare-watch`. `git fetch` showed the checkout was 42 commits behind, because CI commits the DB back twice a day. Pulled before reading anything.
2. Got baseline fares for every new leg (Kiwi search) before choosing thresholds. The pattern is to set the threshold a little under the observed floor.
3. Traced a config key end to end (config → runner → dashboard.py → data.json → index.html) before adding any new key.
4. Read the helper that the Europe filter depends on. `country_of()` looks codes up in `airports.json`, which had only **118 entries**: no ROM, MIL, TFS or TYO. A country whitelist would have silently thrown away most European cities, with no error. I merged Travelpayouts' public `cities.json` + `airports.json` (no token needed), with hand-curated entries winning. That took it to 10,581 codes.
5. Moving `current_base` MEX→LON re-templates every `"{BASE}"` string. The Mexico routes would have quietly become `LON→YYZ` and `LON→LON`. I pinned those routes to `MEX` first, so their labels, and so their daily_min history, didn't change.
6. The month gap can't be expressed in a corridor, so I added a dashboard-only `combos` section. It takes the cheapest first leg per day, walks a running minimum alongside the second-leg dates, and shows the result next to the direct one-way. Tested the gap boundary explicitly.
7. Used `minimised: true` for display only, kept separate from `alerts_enabled`, so each knob does one thing. Charts in a closed `<details>` are drawn when it first opens, because a canvas with no size lays out at 0.
8. Pushed, ran the workflow with `workflow_dispatch`, then checked the live Pages site: the rows, the combos, and zero console errors.

## Judgment calls
- **No alerts on combos.** Each leg already alerts on its own threshold. A combined alert would double-notify.
- **Inspiration alerts left off.** The 31-day Europe list is for browsing. A median alert there would be noise.
- **Didn't switch the TP market from `us`.** The AUS corridors have worked on it. The first live run returned 159 Europe fares, so there was no need.
- **Didn't fix the failing `test_cli_run_corridors_only_skips_inspiration`.** It was already failing before any change (it runs on the real clock against example windows that have now passed). Reported it instead.

## Reusable rule
Before you trust a filter, open the lookup table it depends on and count its rows. Before you change a value that gets templated into other config, find every place it's substituted and pin the ones that must not move.
