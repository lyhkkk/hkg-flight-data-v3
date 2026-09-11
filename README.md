# HKG Flight Data v3

A flight information retrieval system for Hong Kong International Airport (HKIA).
The base package uses only the Python 3.7+ standard library and provides:

- Terminal flight workbench (optional Textual UI, stdlib plain-text fallback)
- Web dashboard with 30-second auto-refresh polling
- CLI commands for searching flights and listing departures/arrivals

## Requirements

- Python 3.9 or newer (base package, no third-party packages required)
- Enhanced terminal UI: the optional `.[tui]` install group (adds Textual)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/lyhkkk/hkg-flight-data-v3.git
cd hkg-flight-data-v3

# Install the full terminal workbench (adds Textual)
python -m pip install ".[tui]"

# Start the interactive terminal workbench (auto backend)
python -m hkg_flight

# Explicit backends
python -m hkg_flight tui --ui textual   # require enhanced UI (fails if missing)
python -m hkg_flight tui --ui plain     # stdlib line-command fallback

# TUI without the 30-second background poller
python -m hkg_flight tui --no-poll

# Start the web dashboard on http://127.0.0.1:8080
python -m hkg_flight web

# Start the web dashboard on a custom port
python -m hkg_flight web --port 9000
```

The bare entry (`python -m hkg_flight`) auto-selects the enhanced UI when
Python, Textual and an interactive terminal are available, otherwise it prints
the reason and uses plain mode. `auto` never installs dependencies.

## CLI Commands

```bash
# Search for a flight by flight number (e.g. CX759)
python -m hkg_flight query CX759              # Compact one-line result
python -m hkg_flight query CX759 --details   # Full flight details

# Search for a flight on a specific date
python -m hkg_flight query CX759 2026-08-16

# Search by airline code (2 letters) — all CX flights
python -m hkg_flight query CX

# Search by gate or HKIA stand (stand prefixes: W/N/R/S/E/D/X)
python -m hkg_flight query G28
python -m hkg_flight query W63

# Short flight numbers such as BA15 are treated as flight numbers
python -m hkg_flight query BA15

# Search including codeshare flights
python -m hkg_flight query 30 --codeshare

# List today's departures
python -m hkg_flight departures

# List departures for a specific date
python -m hkg_flight departures 2026-08-16

# List today's arrivals
python -m hkg_flight arrivals

# List arrivals for a specific date
python -m hkg_flight arrivals 2026-08-16

# Show gate/stand changes away from the original assignment
python -m hkg_flight alerts

# Clear cache
python -m hkg_flight clear-cache
python -m hkg_flight clear-cache 2026-08-16
python -m hkg_flight clear-cache --yes  # Skip confirmation
```

Dates use `YYYY-MM-DD` format. If no date is given for `query`, it searches today —
plus the neighbouring day between 22:00–01:59 HKT, so late-night and
early-morning flights are still found.
If no date is given for `departures` / `arrivals`, the current date is used.

### Query output & pagination

Output follows the width of your terminal (the `COLUMNS` variable is honoured),
and **no line is ever wider than the terminal**, so the shell never wraps a row
in the middle of a value such as `G30`:

- **80 columns or more** — one row per flight under a column header.
- **Narrower** (a phone-sized window) — the header is dropped and each flight
  takes two lines, keeping every field readable instead of squeezing six
  columns onto one line.

When a query matches an airline code (e.g. `query CX`) or returns more than 10
flights, results are shown as a paginated table with **10 flights per page**.
The footer shortens itself to fit narrow terminals:

| Key / Input | Action |
| --- | --- |
| `Enter` / `n` | Next page |
| `p` | Previous page |
| `1`-`9`... | Jump to page number |
| `q` | Quit the pager |

For a single flight, the default query output is also one compact row. Use
`query <flight> --details` (or `-d`) when the labeled full view is needed.

## TUI Controls

In the terminal workbench:

| Key | Action |
| --- | --- |
| `1` / `2` / `5` / `6` | Departures / Arrivals / Alerts / Airlines |
| `/` | Enter search for the current page (flight/alert pages) |
| `Enter` | Open detail (flight/alert) or apply airline filter (airlines page) |
| `Esc` | Close panel → clear page filter → return from auxiliary page |
| `↑` `↓` `PgUp` `PgDn` `Home` `End` | Move selection and scroll |
| `←` / `→` | Page backwards / forwards (list focus) |
| `Tab` / `Shift+Tab` | Cycle focus (list → search → filter) |
| `f` | Toggle the filter panel (status filter) |
| `r` / `w` | Refresh / toggle web server |
| `?` | Toggle help |
| `q` / `Ctrl+Q` / `Ctrl+C` | Quit (Ctrl+Q also quits while typing) |

While the search input has focus, letters, digits, `W` and `Q` are typed as
text and do not switch pages, toggle the web server or quit. Submit with
`Enter`, cancel with `Esc`.

In terminals without the enhanced UI (or on non-interactive output), the plain
line-command fallback is used: `1/2/5/6`, `n`/`p`, `/ <terms>`, `detail <N>`,
`r`, `w`, `help`, `q`. Plain mode never emits ANSI color codes; set `NO_COLOR`
to keep statuses as text in every backend.

## Gate / Stand Alerts

An alert marks a flight whose gate or stand has moved away from the value it
was **originally assigned**. The first allocation is the baseline, not news —
every flight gets a gate, so alerting on it would produce hundreds of rows a
day. Only a later divergence alerts:

```
N24 -> -         released   (the position was withdrawn)
N24 -> S47       changed    (moved to a different position)
N24 -> - -> S47  released then re-assigned -> shown as N24 -> S47
```

An alert always shows the flight's original assignment next to its current
value, so a released-then-re-assigned flight reads `N24 -> S47`. A flight that
returns to its baseline (`N24 -> S47 -> N24`) clears its alert, as does one that
departs, lands or is cancelled. Alerts are newest-first, capped at 500, and
scoped to the current data date.

View them with `python -m hkg_flight alerts`, on the workbench's page `5`, or in
the web dashboard's "Gate / Stand Changes" tab.

## Web Dashboard

Start it with:

```bash
python -m hkg_flight web [--port N]
```

The dashboard is available at `http://127.0.0.1:PORT` (default `8080`). It is a
single self-contained page with two views — flights and gate/stand changes —
and refreshes itself every 30 seconds. It exposes JSON API endpoints such as:

- `/api/flights`
- `/api/search`
- `/api/alerts`
- `/api/stats`
- `/api/airlines`

Press `Ctrl+C` in the terminal to stop the web server.

## Cache

Flight data is cached under `~/.hkg_flight_cache/`. The cache is used as a
fallback when the live HKIA API is unavailable, and it stores the current alert
list. The global `--force` option bypasses cached airline metadata for that run;
it does not delete cache files, and polling may still fall back to cached flight
data when the API is unavailable.

## Verification

Run the test suite:

```bash
python -m unittest test_hkg_flight
python -m unittest discover -s . -p "test*.py"
python -m compileall -q hkg_flight tests cleanup_alerts.py
python -m ruff check .
```

The enhanced UI interaction tests (under `tests/`) run when Textual is
installed and are skipped otherwise. CI is the authoritative cross-platform
result (base matrix 3.9/3.11/3.13, enhanced matrix 3.11/3.13 on Linux and
Windows).
