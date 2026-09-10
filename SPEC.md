# HKG Flight Data v3 — Specification

## 1. Overview

A self-contained Python information retrieval system for Hong Kong International Airport (HKG) flight data. Backend continuously polls the official HKIA REST API with polite rate limiting, caches locally, detects changes (especially gate/stand), and generates alerts. Frontend is a terminal flight workbench (optional Textual UI with a stdlib plain fallback), a CLI, and an optional web server mode.

## 2. Architecture

The implementation is a Python package under `hkg_flight/`, executed with
`python -m hkg_flight`. Older single-file diagrams and commands below are
historical and should be read as logical components rather than current file
names.

```
┌─────────────────────────────────────────────────┐
│                   hkg_flight/                    │
│  ┌───────────┐  ┌────────────┐  ┌────────────┐  │
│  │  Backend   │  │  Frontend  │  │ Web Server │  │
│  │ (poller+   │  │ (terminal) │  │ (toggle)   │  │
│  │  cache+    │  │            │  │            │  │
│  │  alerts)   │  │            │  │            │  │
│  └─────┬─────┘  └─────┬──────┘  └─────┬──────┘  │
│        │              │               │          │
│        └──────┬───────┘               │          │
│               │  snapshot bridge      │          │
│               └───────────────────────┘          │
└─────────────────────────────────────────────────┘
         │                           │
    ┌────┴────┐                ┌─────┴─────┐
    │HKIA API │                │  Browser  │
    │(remote) │                │  (web)    │
    └─────────┘                └───────────┘
```

The rebuilt terminal frontend lives under `hkg_flight/terminal/`:

- `session.py` — session lifecycle, command serialization, snapshot bridge
- `state.py` — page/focus/filter/selection state and pure transitions
- `presenter.py` — whitelist search, stable ordering, field projection
- `views.py` — pure string rendering of the four pages, detail, filter, help
- `plain.py` — stdlib line-command fallback and non-TTY output
- `textual_app.py` — optional enhanced UI (requires Textual)
- `theme.tcss` — enhanced UI styles

The UI layer only reads snapshots and posts commands; it never starts threads,
stops servers or calls the API. The poller owns one worker thread and publishes
atomic, defensive snapshots; `request_refresh` coalesces manual and timed
refreshes into a single in-flight request.

## 3. Data Source

### 3.1 API Endpoints

| Endpoint | URL | Use |
|---|---|---|
| Flights (current/future) | `GET /flightinfo-rest/rest/flights?date=YYYY-MM-DD&span=1` | Today and future |
| Flights (past) | `GET /flightinfo-rest/rest/flights/past?date=YYYY-MM-DD&span=1` | Historical |
| Airlines | `GET /flightinfo-rest/rest/airlines` | Airline metadata |

Base URL: `https://www.hongkongairport.com`

### 3.2 Flight Data Fields

Each API response is a list of entries. Each entry has:
- `arrival` (bool): true = arrival, false = departure
- `cargo` (bool): true = cargo flight (skip)
- `date` (string): YYYY-MM-DD
- `list` (array): array of flight objects

Each flight object in `list`:
- `flight` (array): `[{airline, no}]` — codeshare list, first = primary
- `time` (string): HH:MM planned time
- `status` (string): e.g. "Departed 08:54", "At gate 23:42"
- `statusCode` (string|null): internal code
- `origin` (array[string]): IATA codes (arrivals)
- `destination` (array[string]): IATA codes (departures)
- `terminal` (string): T1 or T2 (may be empty)
- `gate` (string): gate number (departures)
- `aisle` (string): aisle letter (departures)
- `hall` (string): arrival hall letter (arrivals)
- `baggage` (string): belt number (arrivals)
- `stand` (string): parking stand (arrivals)

Stand search in CLI query mode accepts HKIA stand identifiers with prefixes
`W`, `N`, `R`, `S`, `E`, `D`, or `X` followed by 1–3 digits. This prevents
short airline flight numbers such as `BA15` or `SQ2` from being classified as
stands.

Real samples contain same-day, same-direction duplicate segments (same flight
number and time, different stand/belt/hall), so the UI row identity is built
from the full projected record, not `{date}_{flight_number}`. The cache/alert
key format is unchanged.

### 3.3 Polite Rate Limiting

- Minimum interval between API calls: **0.6 seconds** (reference uses 0.5s)
- When fetching multiple dates: 0.6s between each date
- Polling cycle for live updates: every **30 seconds** (today's flights only)
- Cache expiry: 5 minutes for today's data, 24 hours for historical

The rate-limit timing is serialized so concurrent callers (poller, airline
loader, web queries) cannot all observe the same free slot.

### 3.4 Fallback Strategy

1. Try live API call
2. On failure: use cached data (if available)
3. Log warning: `⚠ API failed for {date}, using cache (age: {minutes}m)`

## 4. Backend

### 4.1 Cache System

Storage: `~/.hkg_flight_cache/` directory

Files:
- `flights_YYYY-MM-DD.json` — raw API response per date
- `airlines.json` — airline metadata
- `state.json` — last known state of all flights (for change detection)
- `alerts.json` — pending alerts queue

`cache_saved_at` reads the cached file mtime — the local write time, not the
HKIA data-generation time; when the stat is unavailable it is UNKNOWN.

### 4.2 Change Detection

Track state changes for each flight by `{date}_{flight_number}` key:

```
State snapshot per flight:
{
  key: "2026-08-16_CX759",
  flight_number: "CX759",
  date: "2026-08-16",
  time: "08:40",
  type: "departure",
  status: "Boarding",
  terminal: "T1",
  gate: "63",         ← WATCHED
  stand: "W63",       ← WATCHED
  aisle: "E",
  hall: "",
  belt: "",
  last_updated: "2026-08-16T08:30:00"
}
```

**Alert triggers** (only for gate and stand changes):
- Gate changed: `⚠ CX759 GATE: 62 → 63`
- Stand changed: `⚠ CX759 STAND: W62 → W63`
- Alert persists until status becomes `boarding`/`departed`/`arrived`/`landed`

### 4.3 Alert Lifecycle

```
gate/stand change detected
  → alert raised (visible in TUI and web)
  → alert stays active while status ∈ {scheduled, gate closed, boarding soon, final call, est at xx:xx, delayed}
  → alert cleared when status ∈ {boarding, departed, arrived, landed, cancelled}
```

The alert manager exposes a monotonic, read-only `alerts_revision` that
advances whenever the active set changes; the UI consumes that revision, not a
shared mutable flag.

### 4.4 Poller

- When TUI is running: poll today's flights every 30s
- Detect changes by diffing new API response against the in-memory snapshot
- Generate alerts for gate/stand changes
- Write updated state and alerts to disk

One start, one poller chain: the session owns the poller and starts it with a
non-blocking first refresh that runs exactly once. `--no-poll` disables timed
refreshes but still performs one background first refresh; `r` requests a
manual refresh. Requests are coalesced into a single in-flight refresh, and a
failed request still advances the health revision.

## 5. Frontend — CLI/TUI

### 5.1 Entry Point

```bash
python -m hkg_flight                  # Terminal workbench (auto backend)
python -m hkg_flight tui --ui textual # Require enhanced UI
python -m hkg_flight tui --ui plain   # Stdlib line-command fallback
python -m hkg_flight tui --no-poll    # Disable live polling
python -m hkg_flight web              # Start web server
python -m hkg_flight web --port 8080
```

`auto` selects the enhanced Textual UI when Python, Textual and an interactive
terminal are available; otherwise it prints the reason and uses plain mode.
`auto` never installs dependencies.

### 5.2 Workbench Layout

Four pages — departures, arrivals, alerts, airlines — plus a detail overlay, a
filter panel and help. Layout tiers by terminal size: ≥120×24 shows a list
with a side detail panel; 80–119 columns a single list with an overlay detail;
40–79 columns a two-line compact row; below 40 columns or 16 rows a size hint
(with state preserved). Selection and viewport scroll are tracked separately.

### 5.3 Filtering

Press `/` to enter search; the whitelist fields are the flight number,
codeshare numbers, airline code, origin/destination, gate, stand, terminal and
status. Terms are ANDed, fields are ORed within a term, and the flight-number
field is space-normalized so `CX 759` matches `CX759`. Structured filters for
airline (applied from the airlines page) and status (filter panel, `f`) are
kept per page.

### 5.4 Selection & scrolling

`↑`/`↓` move a row at a time, `PgUp`/`PgDn` by viewport, `Home`/`End` to the
ends; `←`/`→` remain page-compatible aliases in list focus. Each page keeps its
selection, offset, search and filters across refreshes; a disappearing selected
row falls back to the nearest neighbour.

### 5.5 Status Display

Statuses show both text and a color category (boarding/departed green, delayed
yellow, cancelled red, etc.). Unknown fields render as `—`; single-color mode
keeps the selection marker and the status text; `NO_COLOR` disables ANSI color
everywhere.

### 5.6 Alert View

Active alerts newest-first, searchable by flight, changed field, before/after
values and status. `Enter` links to the flight detail when the flight is still
in the current data, otherwise the alert's own snapshot is shown. Alert counts
are always the active count, not an unread count.

The web server is toggled from the workbench with `w`; its status is shown as
OFF / ON / ERROR (a busy port reports ERROR, never a false ON).

## 6. Web Server

### 6.1 Toggle

- Press `W` in TUI to start web server (non-blocking, runs in background thread)
- Press `W` again to stop
- Web server status shown in TUI header
- Default port: 8080

### 6.2 Web API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Web UI page |
| `/api/flights?date=YYYY-MM-DD` | GET | All flights for date |
| `/api/search?flight=CX759&date=YYYY-MM-DD` | GET | Search flights |
| `/api/alerts` | GET | Active alerts |
| `/api/stats` | GET | Statistics |
| `/api/airlines` | GET | Airlines list |

### 6.3 Web UI

Single-page dark theme matching HKIA brand colors (#0f1923 background, #faa718 accent). Features:
- Search by flight number
- Filter by date, status, terminal
- Auto-refresh via 30-second browser polling

## 7. CLI Query Mode

Quick one-shot queries without TUI. Query results use one compact row per
flight by default; pass `--details` or `-d` for the labeled full view. Large
result sets and airline-code searches retain the 10-row interactive pager.

```bash
python -m hkg_flight query CX759              # Compact one-line result
python -m hkg_flight query CX759 --details   # Full flight details
python -m hkg_flight query CX759 2026-08-16   # Compact result for date
python -m hkg_flight departures               # Today's departures
python -m hkg_flight arrivals                 # Today's arrivals
python -m hkg_flight alerts                   # Show active alerts
```

## 8. File Structure

```
hkg-flight-data-v3/
├── SPEC.md                    # This file
├── hkg_flight/                # Main package and module entry point
│   └── terminal/              # Rebuilt terminal workbench (session/state/
│                              #   presenter/views/plain/textual_app)
├── tests/                     # unittest suite (terminal + fixtures)
├── README.md                  # Usage documentation
├── test_hkg_flight.py         # Core regression suite
└── cleanup_alerts.py          # Alert maintenance utility
```

The base package is standard-library-only and can be run directly from a
checkout with `python -m hkg_flight`. The diagram above describes logical
components; the implementation is split across the modules under `hkg_flight/`.

`state.json` is reserved for the documented flight-state snapshot contract. The
current poller compares its in-memory records during a process lifetime; using
that cache for cross-restart change detection remains a separate future task.

## 9. Dependencies

- Python 3.7+ (base package, standard library only)
- Optional `.[tui]` extra: `textual>=8,<9` (requires Python 3.9+)
- Uses: `json`, `urllib`, `os`, `sys`, `time`, `threading`, `http.server`, `datetime`, `signal`, `collections`

The whole distributed `hkg_flight/` source (including the Textual adapter) must
remain parseable by Python 3.7; the Textual import happens only after the
backend selector has chosen the enhanced UI.

## 10. Implementation Notes

- Threading: poller runs in a daemon thread, web server runs in a daemon thread
- Thread safety: `threading.Lock` for shared state; snapshots are defensive copies
- Graceful shutdown: every exit path runs through the session `finally` cleanup
- Terminal resize handling for TUI
- Data freshness: a snapshot is STALE after `max(2 × poll_interval, 60s)`;
  request failures are marked ERROR without waiting for the stale threshold
