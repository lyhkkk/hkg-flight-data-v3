# HKG Flight Data v3

A single-file flight information retrieval system for Hong Kong International Airport (HKIA).
It uses only the Python 3.7+ standard library and provides:

- Curses TUI (with a plain-text fallback for terminals without curses)
- Web dashboard with auto-refresh
- One-shot CLI commands for searching flights and listing departures/arrivals

## Requirements

- Python 3.7 or newer
- No third-party packages required

## Quick Start

Run from the directory containing `hkg_flight.py`:

```bash
# Start the interactive TUI (default)
python hkg_flight.py

# Start the web dashboard on http://localhost:8080
python hkg_flight.py --web

# Start the web dashboard on a custom port
python hkg_flight.py --web --port 9000

# TUI without the 30-second background poller
python hkg_flight.py --no-poll
```

## CLI Commands

```bash
# Search for a flight by flight number (e.g. CX759)
python hkg_flight.py query CX759

# Search for a flight on a specific date
python hkg_flight.py query CX759 2026-08-16

# List today's departures
python hkg_flight.py departures

# List departures for a specific date
python hkg_flight.py departures 2026-08-16

# List today's arrivals
python hkg_flight.py arrivals

# List arrivals for a specific date
python hkg_flight.py arrivals 2026-08-16

# Show active gate/stand change alerts
python hkg_flight.py alerts
```

Dates use `YYYY-MM-DD` format. If no date is given, the current date is used for
`departures` / `arrivals`.

## TUI Controls

In the curses interface:

| Key | Action |
| --- | --- |
| `1` | Search flight |
| `2` | View flights by date |
| `3` | Show departures |
| `4` | Show arrivals |
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
| `↑` / `↓` | Scroll through the current page |
| `Home` / `End` | Jump to first / last page |

In terminals without curses support, a simpler text menu is used; follow the
on-screen prompts.

## Web Dashboard

Start it with:

```bash
python hkg_flight.py --web [--port N]
```

The dashboard is available at `http://localhost:PORT` (default `8080`). It
auto-refreshes via SSE and exposes JSON API endpoints such as:

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

The file has been checked with:

```bash
python -c "import py_compile; py_compile.compile('hkg_flight.py', doraise=True)"
```

It is a valid UTF-8 Python 3 script (declared as `utf-8`, no BOM) and compiles
without syntax errors.