# fare-watch

Personal, two-tier flight-fare monitor. Solo-user, Python 3.11+, SQLite, no framework.

- **Tier 1 — discovery (free):** Travelpayouts / Aviasales **Data API** (cached prices).
  "Inspiration" scans from your current base to anywhere (or a region whitelist),
  under a price ceiling, within a horizon — plus corridor price-history seeding.
- **Tier 2 — verification (paid, gated):** **Duffel** live mode for real bookable
  fares, used only for your fixed corridor watchlist and the top-N Tier 1
  candidates. Never open-ended. **Duffel live mode is billed and is double-gated —
  it cannot charge without explicit opt-in (see below).**

Alerts go to Telegram (SMTP fallback stub). A static Chart.js dashboard publishes
from `/docs` via GitHub Pages. GitHub Actions run it on a schedule and commit the
SQLite DB back to the (private) repo.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install pyyaml                 # only runtime dependency
cp .env.example .env               # fill in tokens (never commit .env)

# Try it end-to-end with recorded fixtures — no token, no network, no charges:
FAREWATCH_FAKE_TP=1 python monitor.py run --tier1-only --dry-run
```

Then point it at the live Data API by exporting `TP_TOKEN` and dropping
`FAREWATCH_FAKE_TP`.

## CLI

```bash
python monitor.py run [--tier1-only] [--dry-run] [--corridors-only]  # scan, alert, export dashboard
python monitor.py set-base <IATA>                  # e.g. set-base GDL
python monitor.py report                           # terminal summary
python monitor.py backfill --route MEX-LHR [--months N]  # Tier 1 seed for one route
```

- `--tier1-only` — Travelpayouts discovery + corridor pricing only (no Duffel).
- `--dry-run` — uses Duffel **test-mode** keys and **fake-logs** alerts (never posts).
- `--corridors-only` — skips inspiration discovery entirely (no `city_directions` calls);
  runs corridor + deadline-watch pricing only.
- `backfill --months N` — how many months ahead (from today) to seed for the route;
  defaults to 3.
- `FAREWATCH_FAKE_TP=1` — use the bundled fixtures instead of the network (offline demo/CI-less).

## Configuration (`config.yaml`)

`current_base` is a single IATA code; `set-base` rewrites it. Every route templated
with `{BASE}` resolves to it. Highlights (see `config.example.yaml` for the full,
commented file):

- **corridors** — `origin`/`destination`, `date_windows` (explicit `A:B` ranges or
  `"any Fri-Mon in 2026-09"`), `trip_type`, `cabin`, `max_price`, `alert_threshold`,
  `flex_days` (±N around anchors), and `origin_variants` (e.g. UK legs also check DUB, AMS).
- **deadline_watches** — `destination`, `must_arrive_by`, `max_price` ("get me home by X under Y").
- **inspiration** — `origins: ["{BASE}"]`, `horizon_weeks`, `price_ceiling`,
  optional `region_whitelist` (country codes like `US`/`GB` or explicit IATA), `top_n_to_verify`.
- **cost_guardrails** — `max_duffel_searches_per_day` (default 100) with hard stop +
  logged warning; spend tracked at `$0.005/search`.
- **alerting** — Telegram on/off, digest mode, median lookback/ratio, dedupe window/band.

## Alerting

Fires when a fare is **below a threshold** OR **below 80% of the trailing 30-day median**
for that route. For corridors the threshold is `alert_threshold` (falling back to
`max_price`) and only fares matching the corridor's `date_windows` / `trip_type` are
considered; for deadline watches it's `max_price`, and only departures on or before
`must_arrive_by` are considered. Dedupe suppresses repeats for the same route + price-band
within 24h. Optional `digest_mode` batches a run's alerts into one message. Failed
deliveries (missing creds, network error, no channel enabled) are **not recorded**, so
they're retried on the next run rather than silently dropped.

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the environment (never hardcoded).

## The Duffel gate (why you won't get surprise charges)

Tier 2 is **off** in this build. A full `run` (without `--tier1-only`) executes Tier 1,
logs what it *would* verify, and stops before any billed call. Turning Duffel on requires
**both**:

1. config `duffel.live_confirmed: true`, and
2. env `DUFFEL_ENABLE_LIVE=1`.

Even with the gate open, the live request is a Phase-2 `NotImplementedError` until
implemented — so no accidental charge is possible today. `test_gates.py` locks this in.

## Scheduling (GitHub Actions)

- `.github/workflows/inspiration.yml` — 1×/day, full scan (Tier 1, inspiration + corridors).
- `.github/workflows/corridors.yml` — 2×/day, runs `--tier1-only --corridors-only` (corridors +
  deadline watches only — inspiration discovery is skipped so it stays a once-a-day scan;
  Tier 1 until Duffel is enabled per the comment in the file).

Both commit `fare_watch.db` + `docs/data.json` back to the repo. Add secrets in
**Settings → Secrets and variables → Actions**: `TP_TOKEN`, `TP_MARKER` (optional),
`DUFFEL_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Keep the repo **private**
(the committed DB contains your watchlist).

## Dashboard

`docs/index.html` (static + Chart.js) reads `docs/data.json`: per-corridor price-history
line charts with a threshold line, current-cheapest table with deep links, the inspiration
shortlist, and estimated Duffel spend this month. Publish via **Settings → Pages →
Deploy from branch → `/docs`**.

## Tests

```bash
pip install pytest
pytest -q          # Tier 1 is fully tested against recorded fixtures; no network
```

## Layout

```
monitor.py            CLI shim -> farewatch.cli
farewatch/            config, models, db, corridors, inspiration, alerts, spend,
                      report, dashboard, runner, notify/, providers/
  providers/          travelpayouts (Tier 1), duffel (Tier 2, gated stub), http
docs/                 index.html + data.json (GitHub Pages)
tests/                pytest suite + recorded fixtures
.github/workflows/    inspiration.yml, corridors.yml
docs/superpowers/plans/2026-07-09-fare-watch.md   full implementation plan
```

## Status / roadmap

- **Done (Phase 1):** Tier 1 end-to-end, storage, alerting, dashboard, CLI, scheduling,
  gated stubs — all tested against fixtures.
- **Phase 2 (gated, needs your go-ahead on Duffel billing):** live Duffel verification,
  flip `corridors.yml` off `--tier1-only`, optional seats.aero award module.

## Data notes

- Travelpayouts requests always send `market`/`currency` explicitly (default `us`/`usd`);
  the API defaults to the `ru` market otherwise.
- The cached Data API has no true price history — history accrues from daily runs going forward.
- `farewatch/data/airports.json` is a curated IATA→country subset for region filtering;
  refresh from `https://api.travelpayouts.com/data/en/airports.json` as needed.
```
