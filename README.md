# HKG Flight Data v3

A flight information retrieval system for Hong Kong International Airport (HKIA).
It uses only the Python 3.7+ standard library and provides:

- Curses TUI (with a plain-text fallback for terminals without curses)
- Web dashboard with 30-second auto-refresh polling
- CLI commands for searching flights and listing departures/arrivals

## Requirements

- Python 3.7 or newer
- No third-party packages required

## Quick Start

```bash
# Clone the repository
git clone https://github.com/lyhkkk/hkg-flight-data-v3.git
cd hkg-flight-data-v3

# Start the interactive TUI (default)
python -m hkg_flight

# Start the web dashboard on http://127.0.0.1:8080
python -m hkg_flight web

# Start the web dashboard on a custom port
python -m hkg_flight web --port 9000

# TUI without the 30-second background poller
python -m hkg_flight tui --no-poll
```

## CLI Commands

```bash
# Search for a flight by flight number (e.g. CX759)
python -m hkg_flight query CX759

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

# Show active gate/stand change alerts
python -m hkg_flight alerts

# Clear cache
python -m hkg_flight clear-cache
python -m hkg_flight clear-cache 2026-08-16
python -m hkg_flight clear-cache --yes  # Skip confirmation
```

Dates use `YYYY-MM-DD` format. If no date is given for `query`, it searches D-1, D, and D+1.
If no date is given for `departures` / `arrivals`, the current date is used.

### Query output & pagination

When a query matches an airline code (e.g. `query CX`) or returns more than 10
flights, results are shown as a compact list with **10 flights per page**:

| Key / Input | Action |
| --- | --- |
| `Enter` / `n` | Next page |
| `p` | Previous page |
| `1`-`9`... | Jump to page number |
| `q` | Quit the pager |

## TUI Controls

In the curses interface:

| Key | Action |
| --- | --- |
| `1` | Show departures |
| `2` | Show arrivals |
| `5` | Show active alerts |
| `6` | Show airlines |
| `W` | Start / stop the web server |
| `Q` | Quit |

While viewing a flight list:

| Key / Input | Action |
| --- | --- |
| Type any text | Filter by flight number, route, etc. |
| `Backspace` | Remove the last filter character |
| `Esc` | Clear the current filter / go back |
| `←` / `→` | Previous / next page |
| `Home` / `End` | Jump to first / last page |

Note: `1`, `2`, `5`, `6`, `W` and `Q` are view shortcuts and cannot be typed
into the filter. In the curses TUI, other printable characters are appended to
this filter; Backspace removes the last character and Escape clears it.

In terminals without curses support, a simpler text menu is used; follow the
on-screen prompts.

## Web Dashboard

Start it with:

```bash
python -m hkg_flight web [--port N]
```

The dashboard is available at `http://127.0.0.1:PORT` (default `8080`). It
auto-refreshes every 30 seconds and exposes JSON API endpoints such as:

- `/api/flights`
- `/api/search`
- `/api/alerts`
- `/api/stats`
- `/api/airlines`

Press `Ctrl+C` in the terminal to stop the web server.

## Cache

Flight data is cached under `~/.hkg_flight_cache/`. The cache is used as a
fallback when the live HKIA API is unavailable, and it stores alert state and
polling history.

## Verification

Run the test suite:

```bash
python -m unittest test_hkg_flight
```

All 82 tests should pass.
