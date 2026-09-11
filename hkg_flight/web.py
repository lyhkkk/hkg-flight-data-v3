"""
HKG Flight Data v3 - Web Server Module.

A small stdlib HTTP server exposing a JSON API and a single-page dashboard.
The dashboard shows two views - flights and gate/stand changes - and refreshes
itself every 30 seconds. Rendering lives entirely in the browser; the server
only ever sends JSON (plus the one static page).
"""

import json
import threading
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .utils import (
    log,
    normalize_flight_number,
    normalize_flights,
    sort_flights,
    today_str,
    validate_date,
)


class _HTTPServer(ThreadingHTTPServer):
    """HTTP server that does not reuse addresses, so a busy port fails loudly."""

    allow_reuse_address = False


class WebServer(object):
    """HTTP server providing the flight data API and dashboard."""

    def __init__(self, poller, api, alert_manager, port=8080, host="127.0.0.1"):
        self.poller = poller
        self.api = api
        self.alert_manager = alert_manager
        self.port = port
        self.host = host
        self._server = None
        self._thread = None

    def running(self):
        """True while the server socket is bound."""
        return self._server is not None

    def start(self):
        """Bind and serve in a background thread; False when the port is busy."""
        try:
            self._server = _HTTPServer((self.host, self.port), self._make_handler())
            self._thread = threading.Thread(
                target=self._server.serve_forever, daemon=True)
            self._thread.start()
            log("Web server started on {}:{}".format(self.host, self.port))
            return True
        except OSError as exc:
            log("Failed to start web server: {}".format(exc))
            return False

    def stop(self):
        """Shut the server down (idempotent)."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            log("Web server stopped")

    # -- API -------------------------------------------------------------
    def get_stats(self):
        """Health of the data feed, for the dashboard status bar."""
        snap = self.poller.snapshot() if self.poller else {}
        return {
            "time": datetime.now().isoformat(timespec="seconds"),
            "date": snap.get("records_date", ""),
            "source": snap.get("source", "none"),
            "refreshing": snap.get("refreshing", False),
            "error": snap.get("last_error"),
            "flights": len(snap.get("records", [])),
            "alerts": self.alert_manager.active_count() if self.alert_manager else 0,
            "polling": self.poller.enabled if self.poller else False,
        }

    def api_flights(self, params):
        """Flights for a date. Raises ValueError on an invalid date."""
        date_str = params.get("date", [today_str()])[0]
        if not validate_date(date_str):
            raise ValueError("Invalid date format. Use YYYY-MM-DD")

        flight_type = params.get("type", ["all"])[0]
        terminal = params.get("terminal", [None])[0]
        status = params.get("status", [None])[0]

        if self.poller and date_str == today_str():
            records = self.poller.today_records
        else:
            raw = self.api.fetch_flights(date_str)
            records = sort_flights(normalize_flights(raw)) if raw else []

        if flight_type in ("arrival", "departure"):
            records = [r for r in records if r.get("type") == flight_type]
        if terminal:
            records = [r for r in records if r.get("terminal", "").lower() == terminal.lower()]
        if status:
            records = [r for r in records if status.lower() in r.get("status", "").lower()]
        return records

    def api_search(self, params):
        """Flight-number search. Raises ValueError on an invalid date."""
        flight_number = params.get("flight", [""])[0]
        date_str = params.get("date", [today_str()])[0]
        if not validate_date(date_str):
            raise ValueError("Invalid date format. Use YYYY-MM-DD")
        if not flight_number:
            return []

        raw = self.api.fetch_flights(date_str)
        if not raw:
            return []

        search_no = normalize_flight_number(flight_number)
        return [
            rec for rec in normalize_flights(raw)
            if rec.get("flight_number") == search_no
            or search_no in rec.get("all_flight_numbers", "")
        ]

    def api_alerts(self):
        """Gate/stand changes, newest first."""
        return self.alert_manager.get_active() if self.alert_manager else []

    def api_airlines(self):
        """Airline metadata."""
        return self.api.fetch_airlines()

    # -- page ------------------------------------------------------------
    def web_ui(self):
        """The dashboard (one self-contained page; data arrives over JSON)."""
        return _PAGE

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _send(self, body, content_type, status=200):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _send_json(self, obj, status=200):
                self._send(json.dumps(obj, ensure_ascii=False),
                           "application/json; charset=utf-8", status)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                path, params = parsed.path, urllib.parse.parse_qs(parsed.query)
                routes = {
                    "/": lambda: self._send(server.web_ui(), "text/html; charset=utf-8"),
                    "/api/flights": lambda: self._send_json(server.api_flights(params)),
                    "/api/search": lambda: self._send_json(server.api_search(params)),
                    "/api/alerts": lambda: self._send_json(server.api_alerts()),
                    "/api/stats": lambda: self._send_json(server.get_stats()),
                    "/api/airlines": lambda: self._send_json(server.api_airlines()),
                }
                handler = routes.get(path)
                if handler is None:
                    self._send_json({"error": "Not found"}, 404)
                    return
                try:
                    handler()
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, 400)

        return Handler


_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HKG Flight Data</title>
<style>
  :root {
    --bg: #0e1620;
    --panel: #16212e;
    --panel-2: #1b2836;
    --line: rgba(255,255,255,.08);
    --text: #e6edf3;
    --muted: #8798ab;
    --accent: #faa718;
    --ok: #4ade80;
    --warn: #f5b942;
    --bad: #ef5350;
    --info: #58a6ff;
    --radius: 10px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans CJK SC", sans-serif;
    background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased;
  }
  header {
    position: sticky; top: 0; z-index: 5;
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    padding: 14px 20px; background: rgba(14,22,32,.92); backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--line);
  }
  .brand { font-size: 17px; font-weight: 650; letter-spacing: .2px; }
  .brand b { color: var(--accent); }
  .status { margin-left: auto; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); display: inline-block; margin-right: 6px; vertical-align: middle; }
  .dot.live { background: var(--ok); box-shadow: 0 0 0 3px rgba(74,222,128,.15); }
  .dot.stale { background: var(--warn); }
  .dot.error { background: var(--bad); }
  .status b { color: var(--text); font-weight: 600; }
  button.ghost {
    font: inherit; font-size: 12.5px; color: var(--text); cursor: pointer;
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; padding: 6px 12px;
  }
  button.ghost:hover { border-color: var(--accent); color: var(--accent); }
  .wrap { max-width: 1360px; margin: 0 auto; padding: 16px 20px 48px; }
  .tabs { display: flex; gap: 6px; margin-bottom: 14px; }
  .tab {
    font: inherit; font-size: 13.5px; cursor: pointer; color: var(--muted);
    background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 7px 14px;
  }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); background: rgba(250,167,24,.08); border-color: rgba(250,167,24,.35); }
  .tab .count {
    display: inline-block; min-width: 20px; margin-left: 7px; padding: 0 6px;
    font-size: 11.5px; line-height: 18px; text-align: center;
    background: var(--panel-2); border-radius: 9px; color: var(--muted);
  }
  .tab.active .count { color: var(--accent); background: rgba(250,167,24,.14); }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
  input[type=search], select {
    font: inherit; font-size: 13px; color: var(--text); background: var(--panel);
    border: 1px solid var(--line); border-radius: 8px; padding: 8px 11px;
  }
  input[type=search] { min-width: 240px; flex: 1 1 240px; }
  input[type=search]::placeholder { color: var(--muted); }
  input:focus, select:focus { outline: none; border-color: var(--accent); }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 9px 12px; text-align: left; white-space: nowrap; }
  th { position: sticky; top: 0; background: var(--panel-2); color: var(--muted); font-weight: 600; font-size: 11.5px; text-transform: uppercase; letter-spacing: .5px; }
  tbody tr { border-top: 1px solid var(--line); }
  tbody tr:hover { background: rgba(255,255,255,.025); }
  td.flight { font-weight: 650; }
  td.mono, .mono { font-variant-numeric: tabular-nums; }
  .pill { display: inline-block; padding: 2px 9px; border-radius: 20px; font-size: 11.5px; font-weight: 600; border: 1px solid transparent; }
  .s-scheduled { background: rgba(135,152,171,.14); color: var(--muted); border-color: rgba(135,152,171,.3); }
  .s-boarding  { background: rgba(74,222,128,.13); color: var(--ok);   border-color: rgba(74,222,128,.32); }
  .s-departed  { background: rgba(88,166,255,.13); color: var(--info); border-color: rgba(88,166,255,.32); }
  .s-landed    { background: rgba(74,222,128,.13); color: var(--ok);   border-color: rgba(74,222,128,.32); }
  .s-delayed   { background: rgba(245,185,66,.14); color: var(--warn); border-color: rgba(245,185,66,.32); }
  .s-cancelled { background: rgba(239,83,80,.14);  color: var(--bad);  border-color: rgba(239,83,80,.32); }
  .s-unknown   { background: rgba(135,152,171,.1); color: var(--muted); }
  .dir { color: var(--muted); font-size: 11px; font-weight: 600; margin-right: 5px; }
  .change { font-weight: 650; font-variant-numeric: tabular-nums; }
  .change .to { color: var(--accent); }
  .change .gone { color: var(--bad); }
  .field { color: var(--muted); font-size: 11px; font-weight: 600; margin-right: 6px; }
  .empty { padding: 56px 20px; text-align: center; color: var(--muted); }
  .empty .big { font-size: 30px; opacity: .5; display: block; margin-bottom: 10px; }
  footer { max-width: 1360px; margin: 0 auto; padding: 0 20px 32px; color: var(--muted); font-size: 12px; }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<header>
  <div class="brand"><b>&#9992;</b> HKG Flight Data</div>
  <div class="status">
    <span><span id="dot" class="dot"></span><span id="source">connecting…</span></span>
    <span id="feed"></span>
    <span>Updated <b id="updated">—</b></span>
    <button class="ghost" id="refresh">Refresh</button>
  </div>
</header>

<div class="wrap">
  <div class="tabs">
    <button class="tab active" data-tab="flights">Flights <span class="count" id="count-flights">0</span></button>
    <button class="tab" data-tab="alerts">Gate / Stand Changes <span class="count" id="count-alerts">0</span></button>
  </div>

  <section id="view-flights">
    <div class="filters">
      <input type="search" id="search" placeholder="Search flight, route, gate or stand…">
      <select id="type">
        <option value="all">All flights</option>
        <option value="departure">Departures</option>
        <option value="arrival">Arrivals</option>
      </select>
      <select id="terminal">
        <option value="">All terminals</option>
        <option value="T1">Terminal 1</option>
        <option value="T2">Terminal 2</option>
      </select>
    </div>
    <div class="panel scroll">
      <table>
        <thead><tr>
          <th>Time</th><th>Flight</th><th>Route</th><th>Status</th><th>Gate / Stand</th><th>Term</th>
        </tr></thead>
        <tbody id="flights-body"></tbody>
      </table>
      <div class="empty" id="flights-empty" hidden><span class="big">&#9992;</span>No flights match.</div>
    </div>
  </section>

  <section id="view-alerts" hidden>
    <div class="panel scroll">
      <table>
        <thead><tr>
          <th>Changed</th><th>Flight</th><th>Field</th><th>Change</th><th>Status</th>
        </tr></thead>
        <tbody id="alerts-body"></tbody>
      </table>
      <div class="empty" id="alerts-empty" hidden><span class="big">&#10003;</span>No gate or stand changes.<br>Flights keep their original assignment.</div>
    </div>
  </section>
</div>

<footer id="footer"></footer>

<script>
const STATUS_CLASS = {
  scheduled: "s-scheduled", boarding: "s-boarding", boarding_soon: "s-boarding",
  final_call: "s-boarding", at_gate: "s-boarding", taxiing: "s-departed",
  departed: "s-departed", landed: "s-landed", delayed: "s-delayed",
  estimated: "s-delayed", gate_closed: "s-delayed", cancelled: "s-cancelled"
};
const SOURCE_LABEL = { api: "live API", cache: "cache", memory: "in-memory", none: "no data" };
const SOURCE_DOT = { api: "live", cache: "stale", memory: "error", none: "error" };

const data = { flights: [], alerts: [], stats: {} };
let tab = "flights";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));

function pill(status, category) {
  return `<span class="pill ${STATUS_CLASS[category] || "s-unknown"}">${esc(status) || "—"}</span>`;
}
function changeText(alert) {
  const from = esc(alert.old_value) || "—";
  const to = alert.new_value ? esc(alert.new_value) : '<span class="gone">—</span>';
  return `<span class="change">${from} <span class="to">→</span> ${to}</span>`;
}
// HKIA returns the gate as a bare number but the stand already carries its
// letter (W69, D201), so only the gate needs a prefix.
function positionText(f) {
  if (f.type === "arrival") return esc(f.stand) || "—";
  return f.gate ? "G" + esc(f.gate) : "—";
}

function renderFlights() {
  const q = $("search").value.trim().toLowerCase();
  const type = $("type").value;
  const terminal = $("terminal").value;

  const rows = data.flights.filter(f => {
    if (type !== "all" && f.type !== type) return false;
    if (terminal && (f.terminal || "") !== terminal) return false;
    if (!q) return true;
    return [f.flight_number, f.origin, f.destination, f.gate, f.stand, f.status, f.terminal]
      .some(v => String(v ?? "").toLowerCase().includes(q));
  });

  $("count-flights").textContent = rows.length;
  $("flights-empty").hidden = rows.length > 0;
  $("flights-body").innerHTML = rows.slice(0, 400).map(f => {
    const arrival = f.type === "arrival";
    const place = arrival ? (esc(f.origin) || "N/A") : (esc(f.destination) || "N/A");
    return `<tr>
      <td class="mono">${esc(f.time) || "--:--"}</td>
      <td class="flight">${esc(f.flight_number) || "N/A"}</td>
      <td><span class="dir">${arrival ? "FROM" : "TO"}</span>${place}</td>
      <td>${pill(f.status, f.status_category)}</td>
      <td class="mono">${positionText(f)}</td>
      <td>${esc(f.terminal) || "—"}</td>
    </tr>`;
  }).join("");
}

function renderAlerts() {
  const alerts = data.alerts;
  $("count-alerts").textContent = alerts.length;
  $("alerts-empty").hidden = alerts.length > 0;
  $("alerts-body").innerHTML = alerts.map(a => `<tr>
    <td class="mono">${esc(String(a.raised_at || "").slice(11, 16)) || "--:--"}</td>
    <td class="flight">${esc(a.flight_number) || "?"}</td>
    <td><span class="field">${esc(a.field) || "?"}</span></td>
    <td>${changeText(a)}</td>
    <td>${pill(a.status, a.status_category)}</td>
  </tr>`).join("");
}

function renderStatus() {
  const s = data.stats || {};
  const source = s.source || "none";
  $("dot").className = "dot " + (SOURCE_DOT[source] || "");
  $("source").textContent = SOURCE_LABEL[source] || source;
  $("feed").textContent = (s.date ? s.date + " · " : "") + (s.flights || 0) + " flights";
  $("footer").textContent = s.error ? ("Feed error: " + s.error) : "";
}

function render() { renderFlights(); renderAlerts(); renderStatus(); }

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(path + " → " + res.status);
  return res.json();
}

async function refresh() {
  try {
    const [flights, alerts, stats] = await Promise.all([
      getJSON("/api/flights"), getJSON("/api/alerts"), getJSON("/api/stats")
    ]);
    data.flights = Array.isArray(flights) ? flights : [];
    data.alerts = Array.isArray(alerts) ? alerts : [];
    data.stats = stats || {};
    render();
    $("updated").textContent = new Date().toLocaleTimeString();
  } catch (err) {
    console.error(err);
    $("footer").textContent = "Refresh failed: " + err.message;
  }
}

document.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
  tab = btn.dataset.tab;
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b === btn));
  $("view-flights").hidden = tab !== "flights";
  $("view-alerts").hidden = tab !== "alerts";
}));

["search", "type", "terminal"].forEach(id => $(id).addEventListener("input", renderFlights));
$("refresh").addEventListener("click", refresh);

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""
