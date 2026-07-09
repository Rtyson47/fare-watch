# fare-watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A personal, two-tier flight-fare monitoring CLI: free cached-price discovery (Travelpayouts/Aviasales Data API) feeding paid, bookable verification (Duffel), with SQLite storage, threshold + median alerting, a static dashboard, and GitHub Actions scheduling.

**Architecture:** Tier 1 (free, cached) scans Travelpayouts v2 endpoints for an inspiration shortlist and to seed corridor price history. Tier 2 (paid, gated) verifies the fixed corridor watchlist + the top-N Tier 1 candidates through Duffel live mode — never open-ended. A normalization layer collapses the different TP/Duffel response shapes into one `FareRecord`. Everything persists to `fare_watch.db`; a run exports `docs/data.json` for a Chart.js dashboard and fires Telegram/SMTP alerts.

**Tech Stack:** Python 3.11+ (dev/CI on 3.14), stdlib `sqlite3` + `urllib` (no HTTP framework), `PyYAML` for config, `pytest` for tests. Duffel + Telegram over HTTPS. Dashboard = static HTML + Chart.js (CDN).

## Global Constraints

- **Python 3.11+**, no web framework. HTTP via stdlib `urllib.request`. Only third-party runtime dep: `PyYAML`. Dev dep: `pytest`.
- **Tier 1 = Travelpayouts only. Tier 2 = Duffel only.** Never run open-ended/discovery scans through Duffel.
- **Travelpayouts requests MUST pass `market` and `currency` explicitly** (default `market=us`, `currency=usd`) — the API defaults to the `ru` market otherwise.
- **v2 endpoints for latest + month-matrix; v1 for grouped cheapest.** `/v2/prices/latest`, `/v2/prices/month-matrix`, `/v1/city-directions` (there is no v2 "from-a-city-to-everywhere" endpoint — v1 city-directions is the canonical grouped-cheapest source). `/v1/prices/cheap` available as a secondary grouped source.
- **Duffel live mode is billed.** No live Duffel call may run without the user's explicit go-ahead. Code path is gated (raises unless explicitly enabled); `--dry-run` uses Duffel **test-mode** keys and fake-logs alerts.
- **Cost guardrail:** `max_duffel_searches_per_day` (default 100). Hard stop + logged warning when hit. Track estimated spend at `$0.005/search` in the DB.
- **Secrets via env vars only** — never hardcoded: `TP_TOKEN`, `DUFFEL_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, optional `TP_MARKER`, `SMTP_*`, `SEATS_AERO_API_KEY`.
- **All timestamps ISO-8601 UTC.** All prices stored as `REAL` with an explicit `currency`.
- **Config is the single source of truth.** `{BASE}` templating resolves to `current_base` everywhere. `set-base <IATA>` rewrites `current_base` in `config.yaml` in place.

---

## Design Decisions (resolved ambiguities)

These are interpretation calls made against the spec; documented so the executor doesn't re-litigate them.

1. **`daily_min.date` = the observation calendar date (UTC), `route` = `"ORIGIN-DEST"`.** This gives the "price history" line chart its x-axis (time) and y (cheapest seen that day). Upsert keeps the running minimum for the day.
2. **Median alert bucket = the route** (`ORIGIN-DEST`) over trailing `median_lookback_days` (30) of `daily_min` rows. Config `median_bucket: route | route_month` allows switching to a per-departure-month bucket (`MEX-LHR:2026-09`) for stabler comparisons; default `route`. A median alert only fires once there are `>= median_min_samples` (default 5) daily_min samples in the window.
3. **Deep links are constructed** as Aviasales search URLs (`aviasales_deep_link()`), because the cached Data API endpoints do not all return a booking link. Format: `https://www.aviasales.com/search/{ORIGIN}{DDMM}{DEST}{RRMM}{pax}?marker={TP_MARKER}`. `marker` is optional (env `TP_MARKER`). Duffel offers (Phase 2) carry their real `offer` id / booking link instead.
4. **`region_whitelist`** entries may be 2-letter country codes (matched via a bundled `farewatch/data/airports.json` IATA→country map) or explicit 3-letter IATA codes (matched directly). Unknown codes are excluded when a whitelist is set (logged at debug). The bundled map is a curated subset; a TODO documents refreshing it from `https://api.travelpayouts.com/data/en/airports.json`.
5. **`one_way|return`** is expressed in config as `trip_type: one_way | return`. Internally `one_way: bool`.
6. **Dedupe band** = absolute width bucket: `dedupe_key = f"{route}|{reason}|{int(price // dedupe_band_width)}"`, `dedupe_band_width` default 20 (currency units). "No repeat within 24h" = skip if a row with the same `dedupe_key` exists with `ts >= now - dedupe_window_hours`.
7. **Phase-1 delivery gates Tier 2.** `run --tier1-only` is fully functional now. `run` (full) executes Tier 1 then logs that Tier 2 is gated and stops before any Duffel call, until the user enables it (Phase 2). The guardrail/spend machinery is built now so Phase 2 only wires the client in.

## Fixtures (recorded API shapes)

Stored under `tests/fixtures/`. Field names mirror the real API exactly (verified against the TP reference): v2 endpoints use `value` + `depart_date`/`return_date` and a **list** `data`; v1 endpoints use `price` + `departure_at`/`return_at` and a **dict** `data` keyed by destination.

`tests/fixtures/tp_prices_latest.json` (`/v2/prices/latest`, MEX→LHR):
```json
{
  "success": true,
  "data": [
    {"show_to_affiliates": true, "trip_class": 0, "origin": "MEX", "destination": "LHR",
     "depart_date": "2026-09-11", "return_date": "2026-09-14", "number_of_changes": 1,
     "value": 612, "found_at": "2026-07-08T09:10:32", "distance": 8900, "actual": true},
    {"show_to_affiliates": true, "trip_class": 0, "origin": "MEX", "destination": "LHR",
     "depart_date": "2026-09-18", "return_date": "2026-09-21", "number_of_changes": 0,
     "value": 705, "found_at": "2026-07-08T09:10:32", "distance": 8900, "actual": true}
  ],
  "currency": "usd"
}
```

`tests/fixtures/tp_month_matrix.json` (`/v2/prices/month-matrix`, MEX→LHR, one row per day):
```json
{
  "success": true,
  "data": [
    {"show_to_affiliates": true, "trip_class": 0, "origin": "MEX", "destination": "LHR",
     "depart_date": "2026-09-01", "return_date": "", "number_of_changes": 1,
     "value": 640, "found_at": "2026-07-08T00:06:12", "distance": 8900, "actual": true},
    {"show_to_affiliates": true, "trip_class": 0, "origin": "MEX", "destination": "LHR",
     "depart_date": "2026-09-11", "return_date": "", "number_of_changes": 1,
     "value": 588, "found_at": "2026-07-08T00:06:12", "distance": 8900, "actual": true},
    {"show_to_affiliates": true, "trip_class": 0, "origin": "MEX", "destination": "LHR",
     "depart_date": "2026-09-12", "return_date": "", "number_of_changes": 0,
     "value": 690, "found_at": "2026-07-08T00:06:12", "distance": 8900, "actual": true}
  ],
  "currency": "usd"
}
```

`tests/fixtures/tp_city_directions.json` (`/v1/city-directions`, from MEX to everywhere):
```json
{
  "success": true,
  "data": {
    "BKK": {"origin": "MEX", "destination": "BKK", "price": 388, "transfers": 1,
            "airline": "TG", "flight_number": 975, "departure_at": "2026-08-25T13:35:00Z",
            "return_at": "2026-09-05T18:20:00Z", "expires_at": "2026-07-20T12:20:36Z"},
    "MAD": {"origin": "MEX", "destination": "MAD", "price": 455, "transfers": 0,
            "airline": "UX", "flight_number": 22, "departure_at": "2026-08-14T18:45:00Z",
            "return_at": "2026-08-21T10:15:00Z", "expires_at": "2026-07-18T00:00:00Z"},
    "NYC": {"origin": "MEX", "destination": "NYC", "price": 210, "transfers": 0,
            "airline": "AM", "flight_number": 404, "departure_at": "2026-08-03T07:00:00Z",
            "return_at": "2026-08-10T22:00:00Z", "expires_at": "2026-07-15T00:00:00Z"}
  },
  "error": null,
  "currency": "usd"
}
```

`tests/fixtures/airports_min.json` (test copy of the IATA→country map):
```json
{"BKK": "TH", "MAD": "ES", "NYC": "US", "LHR": "GB", "MEX": "MX", "DUB": "IE", "AMS": "NL"}
```

---

## File Structure

```
fare-watch/
├── README.md
├── pyproject.toml               # metadata + deps (PyYAML; pytest extra)
├── .gitignore                   # .venv, __pycache__, .env, *.pyc  (NOT fare_watch.db — committed per spec)
├── .env.example                 # all secret env var names, no values
├── config.example.yaml          # documented example config
├── config.yaml                  # active config (seeded from example)
├── monitor.py                   # CLI entrypoint (argparse): run / set-base / report / backfill
├── farewatch/
│   ├── __init__.py
│   ├── config.py                # load/validate/mutate config; {BASE} templating; set_base()
│   ├── models.py                # FareRecord dataclass + normalizers (TP v1/v2 -> FareRecord); route_key; deep link
│   ├── db.py                    # schema + DAL for searches/fares/daily_min/alerts/spend
│   ├── corridors.py             # corridor + deadline expansion: date windows, ±flex, "any Fri-Mon in <m>", variants
│   ├── inspiration.py           # Tier 1 discovery scan -> candidate shortlist -> top_n
│   ├── alerts.py                # alert rules (max_price, <ratio*median), dedupe, digest
│   ├── spend.py                 # Duffel guardrail + $0.005/search tracking
│   ├── report.py                # terminal summary
│   ├── dashboard.py             # export docs/data.json
│   ├── runner.py                # orchestrates a run (Tier 1 now; Tier 2 gated hook)
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── http.py              # tiny urllib GET->json helper (injectable for tests)
│   │   ├── travelpayouts.py     # Tier 1 client: prices_latest / month_matrix / city_directions
│   │   └── duffel.py            # Tier 2 STUB — gated, no live calls (Phase 2)
│   ├── notify/
│   │   ├── __init__.py
│   │   ├── telegram.py          # Telegram sendMessage (env token/chat id)
│   │   └── smtp_stub.py         # SMTP fallback stub
│   ├── seats_aero.py            # STUB behind awards.enabled flag; TODOs (Phase 2/optional)
│   └── data/
│       └── airports.json        # curated IATA->country subset (refreshable)
├── docs/                        # GitHub Pages root
│   ├── index.html               # Chart.js dashboard (reads data.json)
│   ├── data.json                # exported each run
│   └── superpowers/plans/2026-07-09-fare-watch.md   # this plan
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # tmp db, sample config, fake HTTP, fixtures loader
│   ├── fixtures/                # recorded API responses (above)
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_db.py
│   ├── test_travelpayouts.py
│   ├── test_corridors.py
│   ├── test_inspiration.py
│   ├── test_alerts.py
│   ├── test_spend.py
│   ├── test_report.py
│   ├── test_dashboard.py
│   └── test_cli.py
└── .github/workflows/
    ├── inspiration.yml          # 1x/day: run --tier1-only, commit db + data.json
    └── corridors.yml            # 2x/day: corridors + deadline watches (Tier 2 once enabled)
```

---

## PHASE 1 — Scaffold + Tier 1 end-to-end (executable now)

### Task 1: Repo scaffold + config

**Files:** Create `pyproject.toml`, `.gitignore`, `.env.example`, `config.example.yaml`, `config.yaml`, `farewatch/__init__.py`, `farewatch/config.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`, `farewatch/data/airports.json`.

**Interfaces produced:**
- `config.load_config(path="config.yaml") -> dict` — parsed, with `{BASE}` resolved throughout via `resolve_base()`.
- `config.resolve_base(obj, base) -> obj` — recursively replaces the literal `"{BASE}"` in strings.
- `config.set_base(iata, path="config.yaml") -> None` — rewrites `current_base` in place (preserves file, validates IATA is 3 A-Z).
- `config.validate_config(cfg) -> list[str]` — returns human-readable problems (empty = valid).

**TDD steps:**
- [ ] Write `tests/test_config.py`: `set_base` rejects `"lhr7"`/`"XX"` (not 3 uppercase letters) and accepts `"LHR"`; after `set_base("LHR")`, `load_config()["current_base"] == "LHR"` and a corridor whose origin was `"{BASE}"` resolves to `"LHR"`; `validate_config` flags a corridor missing `destination`.
- [ ] Run `pytest tests/test_config.py -v` → FAIL (module missing).
- [ ] Implement `farewatch/config.py`:
```python
import re, yaml
IATA_RE = re.compile(r"^[A-Z]{3}$")

def resolve_base(obj, base):
    if isinstance(obj, str):
        return obj.replace("{BASE}", base)
    if isinstance(obj, list):
        return [resolve_base(x, base) for x in obj]
    if isinstance(obj, dict):
        return {k: resolve_base(v, base) for k, v in obj.items()}
    return obj

def load_config(path="config.yaml"):
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    base = cfg.get("current_base", "")
    return resolve_base(cfg, base)

def set_base(iata, path="config.yaml"):
    iata = iata.strip().upper()
    if not IATA_RE.match(iata):
        raise ValueError(f"Not a valid IATA code: {iata!r}")
    with open(path) as f:
        raw = f.read()
    new = re.sub(r"(?m)^current_base:.*$", f"current_base: {iata}", raw, count=1)
    if new == raw and "current_base:" not in raw:
        new = f"current_base: {iata}\n" + raw
    with open(path, "w") as f:
        f.write(new)

def validate_config(cfg):
    problems = []
    if not IATA_RE.match(str(cfg.get("current_base", ""))):
        problems.append("current_base must be a 3-letter IATA code")
    for i, c in enumerate(cfg.get("corridors", []) or []):
        for req in ("origin", "destination"):
            if not c.get(req):
                problems.append(f"corridor[{i}] missing {req}")
    return problems
```
- [ ] Run `pytest tests/test_config.py -v` → PASS.

`config.example.yaml` (also copied to `config.yaml`):
```yaml
current_base: MEX
defaults:
  market: us
  currency: usd
corridors:
  - origin: "{BASE}"
    destination: LHR
    origin_variants: [DUB, AMS]
    date_windows: ["any Fri-Mon in 2026-09"]
    trip_type: return
    cabin: economy
    max_price: 650
    currency: usd
    alert_threshold: 600
    flex_days: 3
deadline_watches:
  - destination: "{BASE}"
    must_arrive_by: "2026-12-24"
    max_price: 600
    currency: usd
inspiration:
  origins: ["{BASE}"]
  horizon_weeks: 8
  price_ceiling: 450
  currency: usd
  market: us
  region_whitelist: []       # e.g. [US, MX, GB, ES] or explicit [BKK, MAD]
  top_n_to_verify: 10
cost_guardrails:
  max_duffel_searches_per_day: 100
  duffel_cost_per_search_usd: 0.005
alerting:
  telegram: {enabled: true}
  smtp: {enabled: false}
  digest_mode: false
  median_lookback_days: 30
  median_alert_ratio: 0.80
  median_bucket: route          # route | route_month
  median_min_samples: 5
  dedupe_window_hours: 24
  dedupe_band_width: 20
awards:
  enabled: false                # seats.aero Pro module (Phase 2/optional)
```

### Task 2: Data model + normalization (`farewatch/models.py`)

**Interfaces produced:**
- `FareRecord` dataclass: `origin, destination, price: float, currency: str, depart_date: str|None, return_date: str|None, carrier: str|None, one_way: bool, source: str, deep_link: str|None, raw: dict`.
- `from_tp_v2_row(row, currency, source) -> FareRecord` (handles `value`, `depart_date`/`return_date`).
- `from_tp_v1_entry(entry, currency, source) -> FareRecord` (handles `price`, `departure_at`/`return_at`, `airline`).
- `route_key(origin, destination) -> str` → `"MEX-LHR"`.
- `aviasales_deep_link(origin, dest, depart_date, return_date=None, marker=None, pax=1) -> str`.

**TDD steps:**
- [ ] Write `tests/test_models.py`: `from_tp_v2_row` maps `value`→`price` and `depart_date`→`depart_date`; `from_tp_v1_entry` maps `price`→`price`, `departure_at`→`depart_date` (date only), `airline`→`carrier`; `route_key("MEX","LHR")=="MEX-LHR"`; `aviasales_deep_link("MEX","LHR","2026-09-11","2026-09-14")` contains `MEX1109LHR1409` and (with marker) `marker=`.
- [ ] Run → FAIL.
- [ ] Implement:
```python
from dataclasses import dataclass, field
from datetime import date

@dataclass
class FareRecord:
    origin: str
    destination: str
    price: float
    currency: str
    depart_date: str | None = None
    return_date: str | None = None
    carrier: str | None = None
    one_way: bool = False
    source: str = ""
    deep_link: str | None = None
    raw: dict = field(default_factory=dict)

def route_key(origin, destination):
    return f"{origin}-{destination}"

def _date_only(s):
    return s[:10] if s else None

def from_tp_v2_row(row, currency, source):
    rd = row.get("return_date") or None
    return FareRecord(origin=row["origin"], destination=row["destination"],
                      price=float(row["value"]), currency=currency,
                      depart_date=_date_only(row.get("depart_date")),
                      return_date=_date_only(rd), one_way=not rd,
                      source=source, raw=row)

def from_tp_v1_entry(entry, currency, source):
    rd = entry.get("return_at") or None
    return FareRecord(origin=entry["origin"], destination=entry["destination"],
                      price=float(entry["price"]), currency=currency,
                      depart_date=_date_only(entry.get("departure_at")),
                      return_date=_date_only(rd), carrier=entry.get("airline"),
                      one_way=not rd, source=source, raw=entry)

def aviasales_deep_link(origin, dest, depart_date, return_date=None, marker=None, pax=1):
    def ddmm(s):
        d = date.fromisoformat(s[:10]); return f"{d.day:02d}{d.month:02d}"
    path = f"{origin}{ddmm(depart_date)}{dest}"
    if return_date:
        path += ddmm(return_date)
    path += str(pax)
    url = f"https://www.aviasales.com/search/{path}"
    return f"{url}?marker={marker}" if marker else url
```
- [ ] Run → PASS.

### Task 3: Storage (`farewatch/db.py`)

**Interfaces produced:**
- `db.connect(path) -> sqlite3.Connection` (row_factory=Row; `init_schema` applied idempotently).
- `db.record_search(conn, tier, origin, dest, depart_date, return_date, source) -> int` (search_id).
- `db.record_fare(conn, search_id, fare: FareRecord) -> int`.
- `db.upsert_daily_min(conn, route, obs_date, price) -> None` (keeps min).
- `db.trailing_daily_min(conn, route, since_date) -> list[float]`.
- `db.record_alert(conn, route, price, reason, channel, dedupe_key) -> None`.
- `db.recent_alert_exists(conn, dedupe_key, since_ts) -> bool`.
- Schema exactly per spec plus `spend`.

**TDD steps:**
- [ ] Write `tests/test_db.py`: fresh db has all 5 tables; `record_search`+`record_fare` round-trips; `upsert_daily_min` twice for same (route,date) keeps the lower price; `recent_alert_exists` true within window, false outside.
- [ ] Run → FAIL.
- [ ] Implement schema + DAL (SQL from the "STORAGE" section of Design Decisions; `upsert_daily_min` uses `ON CONFLICT(route,date) DO UPDATE SET min_price=min(excluded.min_price, daily_min.min_price), ts=excluded.ts`).
- [ ] Run → PASS.

### Task 4: HTTP helper + Travelpayouts client

**Files:** `farewatch/providers/http.py`, `farewatch/providers/travelpayouts.py`, `tests/test_travelpayouts.py`.

**Interfaces produced:**
- `http.get_json(url, params, headers=None, opener=None) -> dict` — builds query string, GETs, parses JSON. `opener` injectable so tests never hit the network.
- `TravelpayoutsClient(token, market="us", currency="usd", get_json=http.get_json)`:
  - `.prices_latest(origin, destination=None, beginning_of_period=None, period_type="month", one_way=False, limit=30) -> list[FareRecord]`
  - `.month_matrix(origin, destination, month) -> list[FareRecord]`
  - `.city_directions(origin) -> list[FareRecord]`
- Every method injects `token`, `currency`, `market` into params (asserts market+currency present).

**TDD steps:**
- [ ] Write `tests/test_travelpayouts.py` using a fake `get_json` that (a) records the params it was called with and (b) returns the matching fixture. Assert: `prices_latest` sends `market=us`, `currency=usd`, `token=...` and returns `FareRecord`s with `price==612.0` and `depart_date=="2026-09-11"`; `city_directions` flattens the dict fixture into 3 records incl. `BKK@388` with `carrier=="TG"`; `month_matrix` returns 3 records. Assert the URL used is the v2/v1 path expected.
- [ ] Run → FAIL.
- [ ] Implement `http.get_json` (urllib) and the client (maps via `from_tp_v2_row` / `from_tp_v1_entry`, sets `deep_link` via `aviasales_deep_link`).
- [ ] Run → PASS.

### Task 5: Corridor + deadline expansion (`farewatch/corridors.py`)

**Interfaces produced:**
- `SearchSpec` dataclass: `origin, destination, depart_date, return_date|None, one_way, cabin, max_price, currency, alert_threshold, tier_hint`.
- `parse_date_window(entry, today) -> list[tuple[str, str|None]]` — handles `"YYYY-MM-DD:YYYY-MM-DD"` (each day in range as depart, no return) and `"any <Dow>-<Dow> in YYYY-MM"` (depart on first DOW, return on second DOW that week).
- `flex_dates(depart, return_, flex) -> list[tuple[depart, return]]` — Cartesian of ±0..flex days on each anchor.
- `expand_corridor(corridor, today) -> list[SearchSpec]` — over `date_windows` × (`[origin] + origin_variants`) × flex.
- `expand_deadline(watch, base, today, horizon_days=120) -> list[SearchSpec]` — one-way into `destination` arriving on/before `must_arrive_by`, from `base`.

**TDD steps:**
- [ ] Write `tests/test_corridors.py`: `parse_date_window("any Fri-Mon in 2026-09", date(2026,7,9))` yields (Fri, following Mon) pairs, first == `("2026-09-04","2026-09-07")`, all Fridays in Sep present; explicit range `"2026-09-10:2026-09-12"` yields 3 one-way depart dates; `flex_dates("2026-09-11","2026-09-14",3)` yields 49 combos incl. the anchor; `expand_corridor` with `origin_variants:[DUB]` produces specs for both `MEX` and `DUB` origins.
- [ ] Run → FAIL.
- [ ] Implement (weekday math via `datetime.date`, DOW name map, `timedelta`). Guard: flex windows clamp to not produce return < depart.
- [ ] Run → PASS.

### Task 6: Inspiration scan (`farewatch/inspiration.py`)

**Interfaces produced:**
- `country_of(iata, airports) -> str|None`.
- `passes_whitelist(dest, whitelist, airports) -> bool` (empty whitelist ⇒ always true; membership by country code or explicit IATA).
- `within_horizon(depart_date, today, horizon_weeks) -> bool`.
- `run_inspiration(tp_client, insp_cfg, today, airports) -> list[FareRecord]` — calls `city_directions` for each origin, filters by `price <= price_ceiling`, horizon, whitelist; returns sorted-by-price shortlist.
- `top_candidates(shortlist, n) -> list[FareRecord]` — the ≤`top_n_to_verify` that WOULD go to Duffel.

**TDD steps:**
- [ ] Write `tests/test_inspiration.py`: with the city_directions fixture, `price_ceiling=400` keeps only `NYC@210` and `BKK@388` (drops `MAD@455`), sorted `[NYC, BKK]`; `region_whitelist=["US"]` keeps only `NYC`; `top_candidates(shortlist, 1) == [NYC]`; horizon filter drops a fabricated far-future depart.
- [ ] Run → FAIL.
- [ ] Implement (load airports via `importlib.resources` from `farewatch/data/airports.json`; horizon compares `date.fromisoformat(depart) <= today + weeks`).
- [ ] Run → PASS.

### Task 7: Alerting (`farewatch/alerts.py`)

**Interfaces produced:**
- `trailing_median(conn, route, today, lookback_days) -> float|None`.
- `evaluate_fare(conn, fare, ctx) -> Alert|None` where `ctx` carries `max_price`, `median_ratio`, `lookback_days`, `min_samples`, `band_width`. Returns an `Alert(route, price, reason, dedupe_key)` for the first satisfied rule (`below_max_price` then `below_median`) else None.
- `dedupe_key(route, reason, price, band_width) -> str`.
- `should_send(conn, alert, window_hours) -> bool` (not `recent_alert_exists`).
- `dispatch(conn, alert, channels, dry_run) -> None` — sends via channels (or fake-logs when `dry_run`), then `record_alert`.
- `collect_or_send(...)` honoring `digest_mode`; `send_digest(conn, alerts, channels, dry_run)`.

**TDD steps:**
- [ ] Write `tests/test_alerts.py`: fare below `max_price` ⇒ reason `below_max_price`; with 6 seeded daily_min of ~600 (median 600) a fare of 470 (<0.8*600=480) ⇒ `below_median`, but 500 ⇒ None; `<min_samples` history ⇒ no median alert; `should_send` false for a dupe within 24h, true after; `digest_mode` collects instead of sending.
- [ ] Run → FAIL.
- [ ] Implement (`statistics.median`; band bucket per Design Decision 6).
- [ ] Run → PASS.

### Task 8: Spend guardrail (`farewatch/spend.py`)

**Interfaces produced:**
- `searches_today(conn, provider, day) -> int`.
- `can_spend(conn, cfg, day) -> bool` (`searches_today < max_duffel_searches_per_day`).
- `record_duffel_search(conn, cfg, day) -> None` (insert spend row at `duffel_cost_per_search_usd`).
- `spend_this_month(conn, provider, month_prefix) -> dict{searches, est_cost_usd}`.
- `GuardrailHit(Exception)` + `guard(conn, cfg, day)` raising it (caller logs warning + hard-stops the Duffel loop).

**TDD steps:**
- [ ] Write `tests/test_spend.py`: with cap 2, after 2 `record_duffel_search`, `can_spend` false and `guard` raises `GuardrailHit`; `spend_this_month` sums cost = `n*0.005`.
- [ ] Run → FAIL. Implement. Run → PASS.

### Task 9: Notifications (`farewatch/notify/`)

**Interfaces produced:**
- `telegram.send(text, token=None, chat_id=None, poster=None) -> bool` — reads env `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` if not passed; `poster` injectable; returns False (logged) if creds missing rather than raising.
- `smtp_stub.send(subject, body) -> bool` — logs `# TODO SMTP` and returns False.
- `notify.channels_from_config(cfg, dry_run) -> list[callable]` — list of `send(text)` callables; in dry_run returns a single fake-logger.

**TDD steps:**
- [ ] Write `tests/test_notify` cases inside `test_alerts.py`/`test_cli.py`: `telegram.send` with a fake `poster` posts to `.../bot<token>/sendMessage` with the chat id; missing creds ⇒ returns False, no post; dry-run channel logs and never posts.
- [ ] Run → FAIL. Implement. Run → PASS.

### Task 10: Report + Dashboard export

**Files:** `farewatch/report.py`, `farewatch/dashboard.py`, `docs/index.html`, `tests/test_report.py`, `tests/test_dashboard.py`.

**Interfaces produced:**
- `report.build_report(conn, cfg, today) -> str` (terminal text: per-corridor cheapest, inspiration shortlist, alerts today, est. Duffel spend this month).
- `dashboard.build_data(conn, cfg, today) -> dict` (schema in Design Decisions §Dashboard).
- `dashboard.export(conn, cfg, today, path="docs/data.json") -> None`.

**TDD steps:**
- [ ] Write `tests/test_dashboard.py`: after seeding a search+fare+daily_min, `build_data` has `base`, a `corridors[0].history` list, `corridors[0].threshold`, an `inspiration` list, and `spend_this_month`; `export` writes valid JSON to a tmp path. `tests/test_report.py`: `build_report` string contains the route and the cheapest price.
- [ ] Run → FAIL. Implement. Run → PASS.
- [ ] Author `docs/index.html`: static page, Chart.js from CDN, `fetch('data.json')`, one line chart per corridor (price history + horizontal threshold line), a "current cheapest" table with deep links, an "inspiration shortlist" table, and a "Duffel spend this month" figure. (Not unit-tested; validated by loading locally.)

### Task 11: Runner + CLI (`farewatch/runner.py`, `monitor.py`)

**Interfaces produced:**
- `runner.run(cfg, conn, today, tier1_only=False, dry_run=False, tp_client=None) -> dict` — Tier 1: inspiration scan + corridor pricing via TP (seeds searches/fares/daily_min), evaluates alerts, dispatches/collects, exports dashboard. If not `tier1_only`: logs "Tier 2 (Duffel) gated — enable in Phase 2" and returns without any Duffel call (Phase-1 gate).
- `monitor.py` argparse: `run [--tier1-only] [--dry-run]`, `set-base <IATA>`, `report`, `backfill --route ORIG-DEST` (Tier 1 month-matrix seed of daily_min history).

**TDD steps:**
- [ ] Write `tests/test_cli.py`: `run --tier1-only --dry-run` with an injected fake TP client (fixtures) creates searches+fares rows, writes `docs/data.json`, records alerts with channel `dry-run`, and makes **zero** network calls; `run` (no `--tier1-only`) logs the gate and creates no `spend` rows; `set-base LHR` updates config; `backfill --route MEX-LHR` populates `daily_min`.
- [ ] Run → FAIL. Implement. Run → PASS.
- [ ] Final: `pytest -q` all green; `python monitor.py run --tier1-only --dry-run` end-to-end against fixtures (via a `FAREWATCH_FAKE_TP=1` switch that loads fixtures instead of live TP) prints a report and writes `docs/data.json`.

---

## PHASE 2 — GATED (do not implement without explicit user go-ahead)

These require enabling **billed Duffel live mode** and/or extra API keys. Outlined, not broken into executable steps, until the user confirms.

- **Duffel Tier 2 client (`providers/duffel.py`):** live offer search for (a) corridor watchlist specs and (b) top-N Tier 1 candidates only. Wrap every search in `spend.guard()`; hard-stop + Telegram warning on `GuardrailHit`. `--dry-run` uses **test-mode** keys and fake-logs. The client raises unless `DUFFEL_ENABLE_LIVE=1` **and** config `duffel.live_confirmed: true` — a double gate so no accidental charge. Normalize Duffel offers to `FareRecord` (real `deep_link`/offer id). Deadline watches run through Duffel too.
- **Scheduling wiring:** flip `corridors.yml` from `--tier1-only` to full `run` once Duffel is enabled; ensure commit-back of `fare_watch.db` + `docs/data.json`.
- **seats.aero award module (`seats_aero.py`):** behind `awards.enabled`. Cached availability endpoints, ≤1000 calls/day cap reusing the spend guardrail pattern. Currently a stub returning `[]` with TODOs.

---

## Self-Review

- **Spec coverage:** two-tier arch (Tasks 4/Phase 2), config incl. set-base/{BASE}/flex/variants/deadline/inspiration/guardrails (Tasks 1,5,8), storage 4 tables + spend (Task 3), alerting max_price + median + dedupe + digest (Task 7), Telegram + SMTP stub (Task 9), scheduling (Task 11 workflows + Phase 2), dashboard (Task 10), CLI modes incl. dry-run/set-base/report/backfill (Task 11), seats.aero stub (Phase 2). Duffel gating honored throughout. ✔
- **Placeholders:** none — interfaces and code are concrete; the only stubs (Duffel, SMTP, seats.aero) are *intentional* and gated by the spec.
- **Type consistency:** `FareRecord` fields, `route_key`, `SearchSpec`, and DAL signatures are referenced identically across tasks.
