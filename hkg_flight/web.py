"""
HKG Flight Data v3 - Web Server Module
HTTP server with REST API and SSE for real-time updates.
"""

import json
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .utils import log, route_text, gate_stand_text, today_str, normalize_flights, sort_flights, filter_records


class WebServer(object):
    """
    HTTP server providing flight data API and web UI.
    Supports Server-Sent Events for real-time updates.
    """

    def __init__(self, poller, api, alert_manager, port=8080):
        self.poller = poller
        self.api = api
        self.alert_manager = alert_manager
        self.port = port
        self._server = None
        self._thread = None
        self._clients = []  # SSE clients

    def running(self):
        """Check if server is running."""
        return self._server is not None

    def start(self):
        """Start the web server."""
        try:
            handler = self._make_handler()
            self._server = ThreadingHTTPServer(("", self.port), handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            log("Web server started on port {}".format(self.port))
            return True
        except OSError as exc:
            log("Failed to start web server: {}".format(exc))
            return False

    def stop(self):
        """Stop the web server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            log("Web server stopped")

    def get_stats(self):
        """Get server statistics."""
        return {
            "time": datetime.now().isoformat(),
            "alerts": self.alert_manager.active_count() if self.alert_manager else 0,
            "clients": len(self._clients),
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
                self.send_header("Access-Control-Allow-Origin", "*")
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
                    self._send_json({"error": "Not found"}, 404)

            def _handle_stream(self):
                """Handle SSE stream."""
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                client = self.wfile
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
                    if client in server._clients:
                        server._clients.remove(client)

        return Handler

    def api_flights(self, params):
        """API: Get flights."""
        date_str = params.get("date", [today_str()])[0]
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
        """Generate web UI HTML."""
        return """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>HKG Flight Data</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1923; color: #fff; }
        .header { background: #1a2a3a; padding: 1rem; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 1.5rem; color: #faa718; }
        .stats { display: flex; gap: 1rem; font-size: 0.9rem; }
        .container { max-width: 1400px; margin: 0 auto; padding: 1rem; }
        .filters { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .filters input, .filters select { padding: 0.5rem; border: 1px solid #333; background: #1a2a3a; color: #fff; border-radius: 4px; }
        .filters input { width: 200px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #333; }
        th { background: #1a2a3a; color: #faa718; }
        tr:hover { background: #1a2a3a; }
        .status { padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.8rem; }
        .status-scheduled { background: #333; }
        .status-boarding { background: #1a5f3f; }
        .status-departed { background: #2a4a3a; }
        .status-cancelled { background: #5f1a1a; }
        .alert-banner { background: #faa718; color: #000; padding: 0.5rem; text-align: center; display: none; }
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
    </div>
    <script>
        const API_BASE = '/api';
        let allFlights = [];

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
            tbody.innerHTML = flights.slice(0, 100).map(f => `
                <tr>
                    <td>${f.time || '--:--'}</td>
                    <td><strong>${f.flight_number || 'N/A'}</strong></td>
                    <td>${f.type === 'arrival' ? 'ARR' : 'DEP'}</td>
                    <td>HKG ${f.type === 'arrival' ? '←' : '→'} ${f.type === 'arrival' ? (f.origin || 'N/A') : (f.destination || 'N/A')}</td>
                    <td><span class="status status-${f.status_category || 'scheduled'}">${f.status || 'N/A'}</span></td>
                    <td>${f.type === 'departure' ? ('Gate ' + (f.gate || '--')) : ('Stand ' + (f.stand || '--'))}</td>
                    <td>${f.terminal || '-'}</td>
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
