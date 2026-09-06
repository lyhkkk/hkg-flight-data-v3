"""
HKG Flight Data v3 - Web Server Module
HTTP server with REST API and SSE for real-time updates.
"""

import json
import re
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .utils import log, route_text, gate_stand_text, today_str, normalize_flights, sort_flights, filter_records


def _validate_date(date_str):
    """Validate date string format (YYYY-MM-DD). Returns True if valid."""
    if not isinstance(date_str, str):
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str))


def _esc(s):
    """Escape HTML special characters to prevent XSS."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")


class WebServer(object):
    """
    HTTP server providing flight data API and web UI.
    Supports Server-Sent Events for real-time updates.
    """

    def __init__(self, poller, api, alert_manager, port=8080, host="127.0.0.1"):
        self.poller = poller
        self.api = api
        self.alert_manager = alert_manager
        self.port = port
        self.host = host
        self._server = None
        self._thread = None
        self._clients = []  # SSE clients
        self._clients_lock = threading.Lock()

    def running(self):
        """Check if server is running."""
        return self._server is not None

    def start(self):
        """Start the web server."""
        try:
            handler = self._make_handler()
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            log("Web server started on {}:{}".format(self.host, self.port))
            return True
        except OSError as exc:
            log("Failed to start web server: {}".format(exc))
            return False

    def stop(self):
        """Stop the web server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            log("Web server stopped")

    def get_stats(self):
        """Get server statistics."""
        with self._clients_lock:
            client_count = len(self._clients)
        return {
            "time": datetime.now().isoformat(),
            "alerts": self.alert_manager.active_count() if self.alert_manager else 0,
            "clients": client_count,
            "polling": self.poller.enabled if self.poller else False,
        }

    def _make_handler(self):
        """Create request handler class."""
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                """Suppress default logging."""
                pass

            def _send_json(self, obj, status=200):
                """Send JSON response."""
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_html(self, html):
                """Send HTML response."""
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_error(self, status, message):
                """Send error response."""
                self._send_json({"error": message}, status)

            def do_GET(self):
                """Handle GET requests."""
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                params = urllib.parse.parse_qs(parsed.query)

                if path == "/":
                    self._send_html(server.web_ui())
                elif path == "/api/flights":
                    self._send_json(server.api_flights(params))
                elif path == "/api/search":
                    self._send_json(server.api_search(params))
                elif path == "/api/alerts":
                    self._send_json(server.api_alerts())
                elif path == "/api/stats":
                    self._send_json(server.get_stats())
                elif path == "/api/airlines":
                    self._send_json(server.api_airlines())
                elif path == "/api/stream":
                    self._handle_stream()
                else:
                    self._send_error(404, "Not found")

            def _handle_stream(self):
                """Handle SSE stream."""
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                client = self.wfile
                with server._clients_lock:
                    server._clients.append(client)

                try:
                    # Send initial data
                    data = json.dumps(server.api_alerts(), ensure_ascii=False)
                    client.write(b"data: " + data.encode("utf-8") + b"\n\n")
                    client.flush()

                    # Keep connection alive
                    while True:
                        time.sleep(1)
                        # Send heartbeat
                        client.write(b":heartbeat\n\n")
                        client.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    with server._clients_lock:
                        if client in server._clients:
                            server._clients.remove(client)

        return Handler

    def api_flights(self, params):
        """API: Get flights."""
        date_str = params.get("date", [today_str()])[0]
        
        # Validate date format
        if not _validate_date(date_str):
            return {"error": "Invalid date format. Use YYYY-MM-DD"}
        
        flight_type = params.get("type", ["all"])[0]
        terminal = params.get("terminal", [None])[0]
        status = params.get("status", [None])[0]

        if self.poller:
            records = self.poller.today_records
            # Filter by date if not today
            if date_str != today_str():
                raw_data = self.api.fetch_flights(date_str)
                if raw_data:
                    records = normalize_flights(raw_data)
                    records = sort_flights(records)
        else:
            raw_data = self.api.fetch_flights(date_str)
            records = normalize_flights(raw_data) if raw_data else []
            records = sort_flights(records)

        # Filter by type
        if flight_type in ("arrival", "departure"):
            records = [r for r in records if r.get("type") == flight_type]

        # Filter by terminal
        if terminal:
            records = [r for r in records if r.get("terminal", "").lower() == terminal.lower()]

        # Filter by status
        if status:
            records = [r for r in records if status.lower() in r.get("status", "").lower()]

        return records

    def api_search(self, params):
        """API: Search flights."""
        flight_number = params.get("flight", [""])[0]
        date_str = params.get("date", [today_str()])[0]
        
        # Validate date format
        if not _validate_date(date_str):
            return {"error": "Invalid date format. Use YYYY-MM-DD"}

        if not flight_number:
            return []

        raw_data = self.api.fetch_flights(date_str)
        if not raw_data:
            return []

        records = normalize_flights(raw_data)
        from .utils import normalize_flight_number
        search_no = normalize_flight_number(flight_number)

        results = []
        for rec in records:
            if rec.get("flight_number") == search_no:
                results.append(rec)
            elif search_no in rec.get("all_flight_numbers", ""):
                results.append(rec)

        return results

    def api_alerts(self):
        """API: Get active alerts."""
        if self.alert_manager:
            return self.alert_manager.get_active()
        return []

    def api_airlines(self):
        """API: Get airlines list."""
        airlines = self.api.fetch_airlines()
        return airlines

    def web_ui(self):
        """Generate web UI HTML with XSS protection and CSS variables."""
        return r"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>HKG Flight Data</title>
    <style>
        :root {
            --bg: #0f1923;
            --panel: #1a2a3a;
            --panel2: #1c232c;
            --border: rgba(255,255,255,.09);
            --text: #e6edf3;
            --muted: #8b98a9;
            --accent: #faa718;
            --ok: #4ade80;
            --warn: #f59e0b;
            --bad: #ef4444;
            --info: #58a6ff;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); }
        .header { background: var(--panel); padding: 1rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); }
        .header h1 { font-size: 1.5rem; color: var(--accent); }
        .stats { display: flex; gap: 1rem; font-size: 0.9rem; color: var(--muted); }
        .container { max-width: 1400px; margin: 0 auto; padding: 1rem; }
        .filters { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .filters input, .filters select { padding: 0.5rem; border: 1px solid var(--border); background: var(--panel); color: var(--text); border-radius: 4px; }
        .filters input { width: 200px; }
        .filters input:focus, .filters select:focus { outline: none; border-color: var(--accent); }
        table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid var(--border); }
        th { background: var(--panel); color: var(--accent); position: sticky; top: 0; }
        tr:hover { background: var(--panel); }
        .status { padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.8rem; display: inline-block; }
        .status-scheduled { background: #333; color: var(--muted); }
        .status-boarding { background: rgba(74,222,128,.16); color: var(--ok); border: 1px solid rgba(74,222,128,.3); }
        .status-departed { background: rgba(88,166,255,.14); color: var(--info); border: 1px solid rgba(88,166,255,.3); }
        .status-cancelled { background: rgba(239,68,68,.16); color: var(--bad); border: 1px solid rgba(239,68,68,.3); }
        .status-delayed { background: rgba(245,158,11,.16); color: var(--warn); border: 1px solid rgba(245,158,11,.3); }
        .empty-state { text-align: center; padding: 3rem; color: var(--muted); }
        .alert-banner { background: var(--accent); color: #000; padding: 0.5rem; text-align: center; display: none; }
        @media (max-width: 768px) {
            .filters { flex-direction: column; }
            .filters input { width: 100%; }
            th, td { padding: 0.3rem; font-size: 0.8rem; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>HKG Flight Data</h1>
        <div class="stats">
            <span id="last-update">Loading...</span>
        </div>
    </div>
    <div class="alert-banner" id="alert-banner"></div>
    <div class="container">
        <div class="filters">
            <input type="text" id="search" placeholder="Search flight...">
            <select id="type-filter">
                <option value="all">All</option>
                <option value="departure">Departures</option>
                <option value="arrival">Arrivals</option>
            </select>
            <select id="terminal-filter">
                <option value="">All Terminals</option>
                <option value="T1">T1</option>
                <option value="T2">T2</option>
            </select>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Flight</th>
                    <th>Type</th>
                    <th>Route</th>
                    <th>Status</th>
                    <th>Gate/Stand</th>
                    <th>Terminal</th>
                </tr>
            </thead>
            <tbody id="flights-body">
            </tbody>
        </table>
        <div id="empty-state" class="empty-state" style="display:none;">No flights found</div>
    </div>
    <script>
        const API_BASE = '/api';
        let allFlights = [];

        function esc(s) {
            return String(s ?? '').replace(/[&<>"']/g, c => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;'
            }[c]));
        }

        async function loadFlights() {
            const res = await fetch(`${API_BASE}/flights`);
            allFlights = await res.json();
            renderFlights();
            document.getElementById('last-update').textContent = 'Updated: ' + new Date().toLocaleTimeString();
        }

        function renderFlights() {
            const search = document.getElementById('search').value.toLowerCase();
            const typeFilter = document.getElementById('type-filter').value;
            const terminalFilter = document.getElementById('terminal-filter').value;

            let flights = allFlights;

            if (search) {
                flights = flights.filter(f =>
                    (f.flight_number || '').toLowerCase().includes(search) ||
                    (f.origin || '').toLowerCase().includes(search) ||
                    (f.destination || '').toLowerCase().includes(search)
                );
            }

            if (typeFilter !== 'all') {
                flights = flights.filter(f => f.type === typeFilter);
            }

            if (terminalFilter) {
                flights = flights.filter(f => f.terminal === terminalFilter);
            }

            const tbody = document.getElementById('flights-body');
            const emptyState = document.getElementById('empty-state');
            
            if (flights.length === 0) {
                tbody.innerHTML = '';
                emptyState.style.display = 'block';
                return;
            }
            
            emptyState.style.display = 'none';
            tbody.innerHTML = flights.slice(0, 100).map(f => `
                <tr>
                    <td>${esc(f.time) || '--:--'}</td>
                    <td><strong>${esc(f.flight_number) || 'N/A'}</strong></td>
                    <td>${f.type === 'arrival' ? 'ARR' : 'DEP'}</td>
                    <td>HKG ${f.type === 'arrival' ? '←' : '→'} ${f.type === 'arrival' ? (esc(f.origin) || 'N/A') : (esc(f.destination) || 'N/A')}</td>
                    <td><span class="status status-${esc(f.status_category) || 'scheduled'}">${esc(f.status) || 'N/A'}</span></td>
                    <td>${f.type === 'departure' ? ('Gate ' + (esc(f.gate) || '--')) : ('Stand ' + (esc(f.stand) || '--'))}</td>
                    <td>${esc(f.terminal) || '-'}</td>
                </tr>
            `).join('');
        }

        document.getElementById('search').addEventListener('input', renderFlights);
        document.getElementById('type-filter').addEventListener('change', renderFlights);
        document.getElementById('terminal-filter').addEventListener('change', renderFlights);

        // Auto-refresh every 30 seconds
        loadFlights();
        setInterval(loadFlights, 30000);
    </script>
</body>
</html>"""
