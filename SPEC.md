# HKG Flight Data v3 — Specification

## 1. Overview

A self-contained Python information retrieval system for Hong Kong International Airport (HKG) flight data. Backend continuously polls the official HKIA REST API with polite rate limiting, caches locally, detects changes (especially gate/stand), and generates alerts. Frontend is a CLI/TUI with filtering, pagination, and optional web server mode.

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
│  │ (poller+   │  │  (TUI)     │  │ (toggle)   │  │
│  │  cache+    │  │            │  │            │  │
│  │  alerts)   │  │            │  │            │  │
│  └─────┬─────┘  └─────┬──────┘  └─────┬──────┘  │
│        │              │               │          │
│        └──────┬───────┘               │          │
│               │  data bus             │          │
│               └───────────────────────┘          │
└─────────────────────────────────────────────────┘
         │                           │
    ┌────┴────┐                ┌─────┴─────┐
    │HKIA API │                │  Browser  │
    │(remote) │                │  (web)    │
    └─────────┘                └───────────┘
```

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

### 3.3 Polite Rate Limiting

- Minimum interval between API calls: **0.6 seconds** (reference uses 0.5s)
- When fetching multiple dates: 0.6s between each date
- Polling cycle for live updates: every **30 seconds** (today's flights only)
- Cache expiry: 5 minutes for today's data, 24 hours for historical

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

### 4.4 Poller

- When TUI is running: poll today's flights every 30s
- Detect changes by diffing new API response against `state.json`
- Generate alerts for gate/stand changes
- Write updated state and alerts to disk

## 5. Frontend — CLI/TUI

### 5.1 Entry Point

```bash
python -m hkg_flight              # Start TUI (default)
python -m hkg_flight web           # Start web server
python -m hkg_flight web --port 8080
python -m hkg_flight tui --no-poll # Disable live polling
```

### 5.2 TUI Layout

```
╔══════════════════════════════════════════════════════════════╗
  ✈ HKG Flight Data — 2026-08-16              [ALERTS: 2] ⚠  ║
╠══════════════════════════════════════════════════════════════╣
  📊 Arrivals: 412 | Departures: 398 | Airlines: 89           ║
  🔄 Last update: 08:30:15 | Next: 08:30:45                   ║
╠══════════════════════════════════════════════════════════════╣
  [1] Search Flight  [2] By Date  [3] Departures  [4] Arrivals ║
  [5] Alerts         [6] Airlines  [W] Web Server   [Q] Quit   ║
╠══════════════════════════════════════════════════════════════╣
                                                              ║
  TIME  FLIGHT   ROUTE           STATUS           GATE/STAND   ║
  ─────────────────────────────────────────────────────────── ║
  08:40 CX 759   HKG→SIN        Boarding          Gate 63 ⚠  ║
  08:45 CX 251   HKG→NRT        Gate Closed       Gate 32     ║
  08:50 HX 535   HKG→BKK        Scheduled         Gate --     ║
  08:55 UO 113   HKG→TPE        Delayed           Gate 15     ║
  ...                                                        ║
                                                              ║
  ◄ 1/12 ►  Page 1 of 12  (↑/↓ to scroll, ←/→ to page)     ║
╚══════════════════════════════════════════════════════════════╝
```

### 5.3 Filtering

In any list view, type to filter:
- `CX` → filter to CX flights
- `SIN` → filter to SIN origin/destination
- `boarding` → filter to boarding status
- `T1` → filter to Terminal 1
- Clear filter: press `Escape` or clear input

### 5.4 Pagination

- 20 flights per page
- Arrow keys: `←` `→` page, `↑` `↓` scroll within page
- `Home`/`End`: first/last page

### 5.5 Status Display Colors

| Status | Color | Icon |
|---|---|---|
| Scheduled | White | ○ |
| Gate Closed | Yellow | ◉ |
| Boarding Soon | Cyan | ◉ |
| Final Call | Magenta | ⚡ |
| Boarding | Green | ✓ |
| Departed | Green dim | → |
| Est at xx:xx | Yellow | ⏱ |
| Delayed | Red | ⚠ |
| Arrived | Green | ✓ |
| Landed | Green dim | ↓ |
| Cancelled | Red strike | ✗ |

### 5.6 Alert View (press 5)

```
╔══════════════════════════════════════════════════════════════╗
  ⚠ ACTIVE ALERTS (2)                                        ║
╠══════════════════════════════════════════════════════════════╣
                                                              ║
  ⚠ CX 759  GATE CHANGE: 62 → 63                             ║
    Status: Boarding | 08:40 HKG→SIN | T1                    ║
    Alert since: 08:25:30                                     ║
                                                              ║
  ⚠ HX 535  STAND CHANGE: W21 → D305                        ║
    Status: Delayed | 08:50 HKG→BKK | T1                    ║
    Alert since: 08:28:15                                     ║
                                                              ║
  Press any key to return...                                  ║
╚══════════════════════════════════════════════════════════════╝
```

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

Quick one-shot queries without TUI:

```bash
python -m hkg_flight query CX759              # Search flight
python -m hkg_flight query CX759 2026-08-16   # Search with date
python -m hkg_flight departures               # Today's departures
python -m hkg_flight arrivals                 # Today's arrivals
python -m hkg_flight alerts                   # Show active alerts
```

## 8. File Structure

```
hkg-flight-data-v3/
├── SPEC.md                    # This file
├── hkg_flight/                # Main package and module entry point
├── README.md                  # Usage documentation
├── test_hkg_flight.py         # Standard-library unittest suite
└── cleanup_alerts.py           # Alert maintenance utility
```

The package is standard-library-only and can be run directly from a checkout with `python -m hkg_flight`. The diagram above describes logical components; the implementation is split across the modules under `hkg_flight/`.

`state.json` is reserved for the documented flight-state snapshot contract. The
current poller compares its in-memory records during a process lifetime; using
that cache for cross-restart change detection remains a separate future task.

## 9. Dependencies

- Python 3.7+ (standard library only)
- No pip install required
- Uses: `json`, `urllib`, `os`, `sys`, `time`, `threading`, `http.server`, `datetime`, `signal`, `collections`

## 10. Implementation Notes

- Use `curses` for TUI (cross-platform fallback to simple print for Windows)
- Threading: poller runs in daemon thread, web server runs in daemon thread
- Thread safety: use `threading.Lock` for shared state
- Graceful shutdown: signal handlers for SIGINT/SIGTERM
- Terminal resize handling for TUI
