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
  alerts.py      gate/stand divergence detection (first allocation is silent)
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

`gate` is a bare number (`"68"`) and only ever appears on departures. `stand`
already carries its zone letter (`"W69"`, `"D201"`, `"S25"`) and only ever
appears on arrivals. Renderers therefore prefix a gate with `G` but show a
stand verbatim.

Real payloads carry the full IATA number in `no` (`{"airline": "CKS", "no":
"K4 701"}`), where `airline` is the 3-letter ICAO code. A numeric-only `no` is
completed with a 2-letter airline code so `query CX759` works either way.

### 3.3 Rate limiting and fallback

- Minimum 0.6 s between API calls; the timing decision is serialized so
  concurrent callers cannot all observe the same free slot.
- Polling cycle: every 30 s, over the board window (§3.4).
- Airline metadata: 24 h cache; `--force` bypasses it for one run.

Fallback order: live API → cached file → previous in-memory snapshot.

### 3.4 Board window

The board shows one or two **service dates**, decided by one rule
(`utils.board_dates`) from a single reading of the clock:

| Hong Kong time | Service dates |
|---|---|
| `22:00–23:59` | today, tomorrow |
| `00:00–01:59` | yesterday, today |
| `02:00–21:59` | today |

A service date starts at midnight, but a day's flying does not: the last
departures of the night leave after 00:00 and the first arrivals of the morning
land before 02:00. A board built from today alone would drop both, so around
midnight it carries the neighbouring day too. The window always contains today,
never reaches more than one day away, and is always ordered earliest-first.

The rule is read from **one** clock reading per cycle. Asking the clock again
mid-fetch could straddle 23:59:59 and label today's window as tomorrow's.

The same rule decides which dates `query` searches (§7), so the board and a
search of it cannot disagree about which days "now" covers.

The board reports its own clock date (`records_date`) and the window it actually
carries (`records_dates`) separately. They differ around midnight, and the
header marks the board `(previous)` only when **today appears in neither** —
that is, when the snapshot is left over from an earlier run. A window that
merely starts yesterday is the current board and is labelled with a span
instead.

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

Flights are tracked per `{date}_{ARR|DEP}_{flight_number}` key. The direction is
part of the identity: HKIA schedules turnaround flights where one number
arrives and departs on the same day (`UA820` lands from LAX at 05:40 and leaves
for BKK at 07:40), and the two must not collapse into a single record.

An alert marks a flight whose **gate** or **stand** has moved away from the
value it was originally assigned. The first allocation is the baseline, not
news — every flight gets a gate, so alerting on it would produce hundreds of
rows a day. Only a later divergence alerts:

```
N24 -> -        released    (the position was withdrawn)
N24 -> S47      changed     (moved to a different position)
N24 -> - -> S47 released then re-assigned -> shown as N24 -> S47
```

An alert shows the flight's **original** assignment next to its current value,
so a released-then-re-assigned flight reads `N24 -> S47`, never `- -> S47`. A
flight that returns to its baseline (`N24 -> S47 -> N24`) is no longer
divergent, so its alert clears. So does a flight that departs, lands or is
cancelled — its position is no longer actionable.

Alerts are stored newest-first and capped at 500. Alerts whose date is not in the
board window (§3.4) are dropped on load and on every refresh, so a long-running
process does not accumulate yesterday's rows — and so a flight that crosses into
the window keeps the alert it already raised.

### 4.3 Alert lifecycle

The manager is written by exactly one thread (the poller) and read by many (the
web handler threads and the UI), so a single lock guards the list. It exposes a
monotonic read-only `alerts_revision()` that advances whenever the set changes;
the UI polls that counter rather than sharing a mutable flag. `snapshot()`
returns per-alert copies, so the poller thread can keep updating the live set
without disturbing a caller that already read it.

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
- Each cycle reads the clock once, takes the board window from it (§3.4) and
  fetches every date in the window, merging the results into one board.

Two things can go partly wrong in a two-date cycle, and neither may be reported
as full success:

- **Half remembered.** If any date came from the cache rather than the API, the
  cycle reports `cache`. Half live and half remembered must not claim to be
  live. Only a window that came entirely from the API reports `api`.
- **Half missing.** If one date fails, the other is still published and the
  error is recorded. Half a board beats an empty one; the failure is visible in
  the header and the exit code rather than hidden by dropping the day.

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

Every front-end renders at the real terminal width (`utils.terminal_width()`,
honouring `COLUMNS`, capped at `MAX_WIDTH = 120`; 78 when the size is unknown,
e.g. piped output). No rendered line is ever wider than that width, so the shell
can never wrap a row in the middle of a value. The CLI and the plain adapter
have no terminal height, so they use the width-only counterpart
`views.is_compact(width)` (true below `views.COMPACT_BELOW = 80`) and take the
same two-line compact row the workbench uses.

The compact tier drops the column header rather than printing a placeholder: a
two-line row splits the columns across two lines, so no single header lines up
with it. The row marker and the route arrow carry the meaning.

Columns are laid out by `views.layout()`, which gives each column a **minimum**
taken from the shared column table (`FLIGHT_COLUMNS` / `ALERT_COLUMNS`) before
sharing the remainder out by weight. A proportional split alone starved the
status column - the longest real status is 26 cells (`At gate 23:47
(06/09/2026)`) - while `T1` and `05:40` sat on space they could not use. When
the minimums cannot all fit, they are dropped and the weights alone decide. The
header and the rows read the same table, so they cannot drift apart; a label is
never given a minimum of its own, because that would shift every column.

The Textual workbench spends `views.CHROME_ROWS` rows (4) on its own bars -
header, nav, search row and footer - and the body gets the rest, so the last
list row is never clipped. Those widgets run edge to edge: `theme.tcss` sets no
horizontal padding, so a widget's content width is exactly the terminal width
the renderer was handed. Textual does not clip a line that is one cell too wide
- it moves whole words onto the next row. That is what split the rule (a run of
`-` with no spaces to absorb the overflow) in two while the widgets were
padded, and what the end-to-end geometry tests now pin: every string the views
produce has to arrive as exactly one screen row. The gutter lives in the
renderer instead. The bars are written as ladders (see §7), so the header
loses its source timestamp before its freshness label, and the footer keeps `q`
even at 20 columns.

A row's route cell carries its direction — `← KIX` arriving from KIX, `→ KIX`
departing for KIX — because one flight number can appear in both directions.
Those two arrows are not in every code page: on a console that cannot encode
them (cp1252, cp437) the plain output replaces each with `?` rather than
failing, so the direction is lost but the row still lines up — one `?` takes
the one cell the arrow would have had. The workbench paints through Textual
rather than `print`, and is not affected.

The gate/stand cell shows a departure's gate as `G68` and an arrival's stand
verbatim as `W63`. The compact row keeps the single-line column order (time,
flight number, status on line 1; route, gate/stand, terminal on line 2), so
widening a terminal never reorders the fields.

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

### 5.5 Time anchor

Departures and arrivals open on the flights that are current **now** — the list
is parked on the earliest row scheduled at or after the board's clock, read in
Hong Kong time. A board with nothing left in the day parks on its last rows
rather than showing an empty screen.

The anchor is a **service date and a time of day**, not a time of day alone.
Around midnight the board carries two dates (§3.4), and `01:30` on its own names
two different flights; anchoring on minutes alone parks the viewport on
yesterday's 01:30 while the user is waiting for tonight's. A row that carries no
date of its own belongs to the date being anchored on — the payload omitted it,
the schedule did not. On a one-date board the date changes nothing.

The anchor follows the clock on every landed refresh until the user takes the
list over: the first manual move, `Home`/`End` or `[`/`]` pins it, and the
search line then reads `Pinned HH:MM` instead of `Now HH:MM`. `t` hands the
list back to the clock. `[` and `]` step exactly one screen — as many rows as
the body currently renders — so the screen after the jump starts where the one
before it ended and no flight is skipped between presses. In search, those keys
type text instead.

Once the list is pinned, the label dates itself whenever the anchor sits on a
date other than the board's own clock date — `Pinned 09-13 01:30` — because
"Pinned 01:30" does not say which night that is. The header carries the span
(`Data date 2026-09-12 +1`) so the board itself never looks like it holds one
day's flights when it holds two.

The anchor is derived from the rows on screen and never hides data: it moves the
viewport, it does not filter. Search, filters and selection keep their meaning.

### 5.6 Status display

Statuses show text plus a colour category (boarding/departed green, delayed
yellow, cancelled red, …). Unknown fields render as `—`; `NO_COLOR` disables
ANSI colour everywhere.

### 5.7 Alert view

Gate/stand divergences newest-first, as an aligned table: when the change was
seen, the flight, the field and its before/after values, and the current status.
Searchable by flight, changed field, before/after values and status. `Enter`
links to the flight detail when the flight is still in the current data,
otherwise the alert's own snapshot is shown. Counts are always the live alert
count, not an unread count.

The web server is toggled from the workbench with `w`; its status shows OFF /
ON / ERROR. A busy port reports ERROR, never a false ON.

## 6. Web Server

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard (dark theme, HKIA accent `#faa718`) |
| `/api/flights?date=&type=&terminal=&status=` | GET | Flights for a date, or the whole board window |
| `/api/search?flight=&date=` | GET | Search flights |
| `/api/alerts` | GET | Gate/stand divergences, newest first |
| `/api/stats` | GET | Feed health (source, dates, flight/alert counts, HKT clock) |
| `/api/airlines` | GET | Airline list |

The dashboard is a single self-contained page with two views — flights and
gate/stand changes — and refreshes itself every 30 s. Rendering happens in the
browser; the server only ever sends JSON.

`/api/flights` with no `date` returns the whole board window (§3.4), sorted
earliest-first. The order is part of the contract, not a convenience: the page
anchors by scanning rows in arrival order, and unsorted rows would park it on
the wrong day. A window that spans midnight therefore arrives as one ordered
board, exactly as the workbench shows it.

`/api/stats` carries `hkt_now` (`HH:MM`), `hkt_minutes` and `hkt_date`, computed
on the server: the board is Hong Kong's, so "now" cannot come from the viewer's
clock. It also carries `dates`, the window the server is serving, which the page
uses to label the span (`2026-09-12 +1`). The flights view parks on the current
flights the same way the workbench does — on load, on every refresh, and on the
`◀` / `▶` keys or buttons, which step one screen of rows. The search row shows
`Now HH:MM` while the view still follows the clock and `Pinned HH:MM` once the
user has scrolled or stepped, dating the label (`Pinned 09-13 01:30`) when the
anchor is not on the board's own date; `Now` re-follows it. A landed refresh
leaves a pinned view where the user left it.

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

Dates use `YYYY-MM-DD`. Without a date, `query` searches the board window
(§3.4): today, plus the neighbouring day between 22:00–01:59 HKT, so late-night
and early-morning flights are found. It is the same rule the board uses, not a
copy of it, so a search cannot look at a different set of days than the board it
searches. A result set covering more than one day is divided by a dated rule
(`-- 2026-09-11 ----`), so the same scheduled time on consecutive days cannot
read as a duplicated row. A stand or gate query that matches nothing falls back
to a flight-number match, so an input such as `D7` never silently hides a
flight. Result sets over 10 rows, and airline-code searches, use a 10-row
interactive pager.

Table output follows the terminal width (see §5.2). At 80 columns or more a
flight is one row under a column header; below that the header is dropped and
each flight takes the two-line compact row, which keeps every field readable
instead of squeezing six columns into a phone-sized window. Headings, the pager
footer and the codeshare hint are written as a ladder through `views.fit()` -
the longest form that fits the width wins, and a form that would wrap is never
used (a footer with nothing that fits is omitted entirely). Ladder strings must
stay free of anything that looks like rich markup (`[n]`), because they are
measured with `views.text_width()`, which strips markup and would under-count
them.

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
└── cleanup_alerts.py       # Inspect / clear the alert cache
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
