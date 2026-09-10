# HKG Flight Data v3 — Specification

## 1. Overview

A self-contained flight information system for Hong Kong International Airport.
A background poller fetches the official HKIA REST API with polite rate
limiting, caches locally, detects gate/stand changes and raises alerts. Three
front-ends read the same snapshots: a terminal workbench (optional Textual UI
with a stdlib plain fallback), a CLI, and an optional web dashboard.

This document describes the system as built. It is a description, not a
constraint: implementation choices belong in the code and its tests.

## 2. Architecture

```
hkg_flight/
  utils.py       pure helpers: dates, status mapping, normalization, text safety
  api.py         HKIA REST client with serialized rate limiting
  cache.py       atomic on-disk JSON cache
  alerts.py      gate/stand change detection and the alert lifecycle
  poller.py      one worker thread; publishes immutable flight snapshots
  cli.py         argument parsing, one-shot queries, entry point
  web.py         HTTP server + single-page dashboard
  terminal/
    presenter.py   projection, whitelist search, stable row identity
    state.py       pure UI reducer (state, rows, action) -> (state, commands)
    views.py       pure string rendering, shared by both front-ends
    session.py     owns the poller, the web toggle and the airline loader
    plain.py       line-command driver (pipes, scripts, NO_COLOR)
    textual_app.py optional enhanced UI (requires Textual)
    theme.tcss     enhanced UI styles
```

Data flow is one-directional:

```
HKIA API -> normalize -> immutable snapshot -> views
                              |
                              +-> diff vs previous snapshot -> alerts
```

The UI layer only reads snapshots and posts commands. It never starts threads,
stops servers or calls the API — `session.py` is the single owner of all three.

## 3. Data Source

### 3.1 Endpoints

| Endpoint | URL | Use |
|---|---|---|
| Flights | `GET /flightinfo-rest/rest/flights?date=YYYY-MM-DD&span=1` | Today and future |
| Airlines | `GET /flightinfo-rest/rest/airlines` | Airline metadata |

Base URL: `https://www.hongkongairport.com`

### 3.2 Response shape

Each response is a list of entries:

- `arrival` (bool) — true = arrival, false = departure
- `cargo` (bool) — cargo entries are skipped
- `date` (string) — `YYYY-MM-DD`
- `list` (array) — flight objects

Each flight object:

- `flight` (array) — `[{airline, no}]`; the first entry is primary
- `time` (string) — `HH:MM` scheduled time
- `status` (string) — e.g. `Dep 00:13`, `At gate 01:06 (11/09/2026)`
- `origin` / `destination` (array of IATA codes)
- `terminal`, `gate`, `aisle`, `hall`, `baggage`, `stand` (strings, may be null)

Real payloads carry the full IATA number in `no` (`{"airline": "CKS", "no":
"K4 701"}`), where `airline` is the 3-letter ICAO code. A numeric-only `no` is
completed with a 2-letter airline code so `query CX759` works either way.

### 3.3 Rate limiting and fallback

- Minimum 0.6 s between API calls; the timing decision is serialized so
  concurrent callers cannot all observe the same free slot.
- Polling cycle: every 30 s (today's flights only).
- Airline metadata: 24 h cache; `--force` bypasses it for one run.

Fallback order: live API → cached file → previous in-memory snapshot.

## 4. Backend

### 4.1 Cache

Directory `~/.hkg_flight_cache/`:

- `flights_YYYY-MM-DD.json` — raw API response per date
- `airlines.json` — airline metadata
- `alerts.json` — active alerts plus retained history

Writes are atomic (temp file + `os.replace`). Reads never raise: a missing or
corrupt file is a cache miss. `cache_saved_at` reports the local file mtime —
when it was written, not when HKIA generated the data — and is UNKNOWN when the
stat is unavailable.

### 4.2 Change detection

Flights are tracked per `{date}_{flight_number}` key. Only **gate** and
**stand** changes raise alerts:

```
⚠ CX759 GATE: 62 → 63
⚠ CX759 STAND: W62 → W63
```

An alert persists while the flight is still pending and is cleared once the
status becomes boarding / departed / arrived / landed / cancelled.

### 4.3 Alert lifecycle

The manager exposes a monotonic read-only `alerts_revision()` that advances
whenever the active set changes; the UI polls that counter rather than sharing
a mutable flag. `snapshot()` returns per-alert copies, so the poller thread can
keep updating the live set without disturbing a caller that already read it.

### 4.4 Poller

- One worker thread; one writer, and `_refresh` never runs concurrently with
  itself. There is no second writer, so no generation counters or late-result
  reordering are needed.
- A manual request arriving mid-refresh returns `already_running` instead of
  queueing, so the refresh slot can never be double-claimed.
- `start(blocking=True)` refreshes on the calling thread before the worker
  starts (used by `web`, which wants data ready). The TUI uses the default
  non-blocking start.
- `--no-poll` disables timed refreshes but still performs one first refresh.
- A failed request still advances the revision, so the UI can show that a
  refresh was attempted.

Records are **published, never mutated**: `normalize_flights` builds a fresh
list of fresh dicts each cycle and nothing writes to it afterwards, so a
snapshot needs only a shallow list copy to stay safe.

## 5. Frontend

### 5.1 Entry points

```bash
python -m hkg_flight                  # Terminal workbench (auto backend)
python -m hkg_flight tui --ui textual # Require enhanced UI
python -m hkg_flight tui --ui plain   # Stdlib line-command fallback
python -m hkg_flight tui --no-poll    # Disable timed polling
python -m hkg_flight web [--port N]   # Web dashboard
```

`auto` selects the enhanced Textual UI when Python, Textual and an interactive
terminal are available; otherwise it prints the reason and uses plain mode.
`auto` never installs dependencies.

### 5.2 Layout

Four pages — departures, arrivals, alerts, airlines — plus a detail overlay, a
filter panel and help. Layout tiers by terminal size: ≥120×24 shows a list with
a side detail panel; 80–119 columns a single list with an overlay detail; 40–79
columns a two-line compact row; below 40 columns or 16 rows a size hint (with
state preserved). Selection and viewport scroll are tracked separately.

### 5.3 Search and filtering

`/` enters search. Whitelisted fields: flight number, codeshare numbers, airline
code, origin/destination, gate, stand, terminal, status. Terms are ANDed, fields
are ORed within a term, and the flight-number field is space-normalized so
`CX 759` matches `CX759`. Structured airline and status filters are kept per
page.

### 5.4 Selection and scrolling

`↑`/`↓` move a row, `PgUp`/`PgDn` by viewport, `Home`/`End` to the ends. Each
page keeps its selection, offset, search and filters across refreshes; a
disappearing selected row degrades visibly to its nearest neighbour and says so.

### 5.5 Status display

Statuses show text plus a colour category (boarding/departed green, delayed
yellow, cancelled red, …). Unknown fields render as `—`; `NO_COLOR` disables
ANSI colour everywhere.

### 5.6 Alert view

Active alerts newest-first, searchable by flight, changed field, before/after
values and status. `Enter` links to the flight detail when the flight is still
in the current data, otherwise the alert's own snapshot is shown. Counts are
always the active count, not an unread count.

The web server is toggled from the workbench with `w`; its status shows OFF /
ON / ERROR. A busy port reports ERROR, never a false ON.

## 6. Web Server

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard (dark theme, HKIA accent `#faa718`) |
| `/api/flights?date=&type=&terminal=&status=` | GET | Flights for a date |
| `/api/search?flight=&date=` | GET | Search flights |
| `/api/alerts` | GET | Active alerts |
| `/api/stats` | GET | Server statistics |
| `/api/airlines` | GET | Airline list |

The dashboard auto-refreshes every 30 s.

## 7. CLI

```bash
python -m hkg_flight query CX759              # Compact one-line result
python -m hkg_flight query CX759 --details    # Full flight details
python -m hkg_flight query CX                 # Airline code (paginated)
python -m hkg_flight query G28                # Gate
python -m hkg_flight query W63                # HKIA stand (prefixes W/N/R/S/E/D/X)
python -m hkg_flight departures [DATE]        # Today's departures
python -m hkg_flight arrivals [DATE]          # Today's arrivals
python -m hkg_flight alerts                   # Active alerts
python -m hkg_flight clear-cache [DATE] [--yes]
```

Dates use `YYYY-MM-DD`. Without a date, `query` searches today; between
22:00–01:59 HKT it also looks at the neighbouring day so late-night and
early-morning flights are found. A stand or gate query that matches nothing
falls back to a flight-number match, so an input such as `D7` never silently
hides a flight. Result sets over 10 rows, and airline-code searches, use a
10-row interactive pager.

## 8. File structure

```
hkg-flight-data-v3/
├── SPEC.md                 # This file
├── README.md               # Usage
├── COMMANDS.md             # Command reference
├── hkg_flight/             # Main package
│   └── terminal/           # Terminal workbench
├── tests/                  # unittest suite + offline fixtures
├── docs/archive/           # Historical design notes and review reports
├── test_hkg_flight.py      # Core regression suite
└── cleanup_alerts.py       # Alert maintenance utility
```

## 9. Dependencies

- Python 3.9+ (base package: standard library only)
- Optional `.[tui]` extra: `textual>=8,<9`

## 10. Design notes

- **Threading**: the poller and the web server each run one daemon thread.
- **Snapshots**: published, never mutated. Readers get shallow copies of the
  list; the records themselves are never written to after publication.
- **Text safety**: untrusted API strings are sanitised once, at the data
  boundary (`utils.clean_text` strips control characters). Renderers therefore
  do not defend themselves again; the markup layer only escapes `[`.
- **Shutdown**: every exit path runs through the session's `finally` cleanup.
- **Freshness**: a snapshot is STALE after `max(2 × poll_interval, 60 s)`;
  request failures are marked ERROR without waiting for the stale threshold.
