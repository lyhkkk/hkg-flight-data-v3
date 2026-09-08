# HKG Flight Data v3 — Code Review Report v4

- **Date**: 2026-09-08
- **Baseline**: HEAD `93b958b` + uncommitted remediation round (12 files, net **-119 lines**)
- **Scope**: Full package `hkg_flight/` (2,543 lines, 10 modules), test suite (1,014 lines, 70 tests), CLI/TUI/Web entry points, docs (README, COMMANDS.md, SPEC.md), root scripts
- **Method**: Full static read of all source files, AST unused-import/dead-code scan, unittest run, live smoke tests (HTTP server on 127.0.0.1:8232, error semantics, SSE removal, bypass_cache persistence), plus adversarial re-verification of the two prior third-party reports (`CODE-REVIEW.html` v2, `CODE-REVIEW-v3.html` v3)
- **Reviewer**: opencode (independent; prior reports used as input, not trusted)

---

## Verdict

**The security baseline is solid, this round's P1 fixes are verified correct, and the codebase is in the cleanest state of its history. The single biggest remaining weakness is that the 70-test suite covers none of the modules that just changed (web, poller, tui) — the fixes are verified by smoke test today but protected by nothing tomorrow.**

14 findings this round: **0 P0, 0 P1, 4 P2, 10 P3/info**. No regressions were introduced by the remediation round; one cosmetic defect from it (collapsed JS newline) was found and fixed during this review.

| Dimension | Grade | Trend vs v3 |
|---|---|---|
| Security | **A-** | ↑ (was B+) |
| Functionality | **B-** | ↑ (was C+) |
| Code quality | **B** | ↑ (was C+) |
| Test coverage | **C+** | → (was B-, see F1: the "58/58" basis was wrong; coverage has structural blind spots) |
| Docs consistency | **B-** | ↑ (was C) |
| Engineering (packaging/CI) | **D** | → (unchanged, deferred by owner decision) |

---

## Part 1 — Verification of the remediation round (12/12 confirmed)

Every item from the agreed plan was re-verified against the working tree, not just by reading the diff:

| # | Fix | Location | Verification |
|---|---|---|---|
| 1 | `0`-key no longer wipes filter; unreachable branches removed | `tui.py:537-554` | Esc-only clear confirmed; printable branch reachable; dead `ch == -1`/`ch == 27` duplicates gone |
| 2 | Fake ↑/↓ scroll keys removed | `tui.py` (scroll had 0 readers) | grep: no `self.scroll` references remain |
| 3 | Invalid date → HTTP 400 | `web.py:104-110,127,160` | Smoke test: `GET /api/flights?date=../../../evil` → `400 {"error": ...}` |
| 4 | Frontend hardened | `web.py:293-307` | try/catch + `res.ok` + `Array.isArray` all present in shipped JS |
| 5 | SSE deleted | `web.py` (was :136-165) | `GET /api/stream` → 404; `_clients`/`_handle_stream` 0 references; docs updated |
| 6 | `_validate_date` single copy | `utils.py:16` | api/cache/web import it; local copies deleted; `import re`/`sys` cleanup confirmed by AST scan |
| 7 | Dead code removed | 5 files | `_make_snapshot`/`_snapshot_changed`/`_esc`/`_attr`/`cmd_date`/`APIClient._lock` → 0 references |
| 8 | `--force` → `bypass_cache` | `cli.py:588`, `api.py:27,87` | Smoke test: alerts.json survives; help text updated |
| 9 | Non-today date + API failure → `[]` | `web.py:133-138` | Smoke test: past date with failing API → `200 []` (was: silently today's data) |
| 10 | `log()` has time | `utils.py:79` | Live output: `[hkg_flight] 2026-09-08 05:38:22 Web server started...` |
| 11 | CLI table truncation | `cli.py:311,366` | `route[:20]`, `status[:18]`, `gate_stand[:12]` in both tables |
| 12 | Docs fixed | COMMANDS.md, README.md, SPEC.md | `--force web` → `--force web` order documented; SSE claim removed; ↑/↓ row removed; reserved-key note added |

**Regression check**: 70/70 tests pass after all changes (`python -m unittest test_hkg_flight`, 0.15s). Web smoke suite passed: 400-on-bad-date, 404-on-removed-stream, 404-on-unknown, idempotent stop/start, alerts persistence.

---

## Findings (current state)

### P2 — should fix soon

**P2-1. Zero test coverage on the modules that just changed.**
The 70 tests cover `utils`, `cache`, `alerts`, `api` (mocked), `cli` query functions, and pagination. Mentions of `web`, `poller`, `tui`, `main()`, `clear_cache`, `force`, `bypass` in the test file: **0 each**. Concretely untested: the 400 path, the N9 `[]`-on-failure path, `bypass_cache` gating, `WebServer.start/stop`, the entire curses/simple TUI. The remediation round's most fragile changes (HTTP semantics, `api_flights` restructure) have no regression guard — today's green suite would stay green even if these broke.
*Recommendation*: add ~10 targeted tests — `api_flights`/`api_search` raising `ValueError`, live-server request smoke (pattern already exists in this review's smoke script), `bypass_cache` flag behavior, `Poller.stop()` terminating.

**P2-2. Alert history grows without bound.** `alerts.py:127` appends to `history` forever; retention depends on someone manually running `cleanup_alerts.py` (root script, dry-run by default). For a long-running poller this is a slow leak plus degrading alert views.
*Recommendation*: cap in `AlertManager.save()` (keep newest 500) — 3 lines.

**P2-3. No packaging or CI.** Still no `pyproject.toml`, no lint config, no CI. "70/70 pass" is a fact only when a human remembers to run it. Deferred by owner decision — recorded here as open debt.

**P2-4. `--force` practical effect is narrow — document or extend it.** `bypass_cache` only gates the airlines fresh-cache read (`api.py:87`); `fetch_flights` never reads cache in the happy path (cache is a fallback on API failure via `poller.py:88`), so `--force departures` is currently a no-op with a reassuring message. Not a bug — the dangerous wipe is gone — but the flag over-promises.
*Recommendation*: either wire `bypass_cache` into the poller's cache-fallback decision, or adjust help text to "skip cached airline data".

### P3 / informational

**P3-1. Dead HTML in web UI.** `web.py` ships `<div id="alert-banner">` (line 251) but no JS ever references it — a leftover from the pre-SSE-deletion design. Either populate it from `/api/alerts` or delete the div.
**P3-2. Web UI is today-only.** SPEC.md §6.3 claims "Filter by date, status, terminal"; the UI has search/type/terminal but no date or status control, and `api_flights` defaults to today. Align spec or add the filters.
**P3-3. `AlertManager.get_active()/get_history()` return live internal list references** (`alerts.py:33-39`) — callers can mutate manager state by accident. Return copies (`list(...)`) or document.
**P3-4. Unused imports in tests**: `patch`, `Poller`, `load_airlines`, `DEFAULT_CACHE_DIR`, `DEFAULT_MIN_API_INTERVAL` (`test_hkg_flight.py:10-37`) — the package-import block doubles as an export check, but these five are pure leftovers.
**P3-5. Inline import in `web.py:170`** (`from .utils import normalize_flight_number` inside `api_search`) — move to the top-level import.
**P3-6. No `--no-color` / `NO_COLOR` support** — ANSI codes are emitted unconditionally (`cli.py`, `tui.py`); piped/redirected output carries escape garbage. Carried over from v2/v3, unactioned.
**P3-7. Curses probe pattern** (`cli.py` `cmd_tui`: `import curses` used only as an availability probe) — lint will flag it; a comment would defuse it.
**Info-1. Simple TUI vs curses TUI key drift** — simple TUI has no `W` web-toggle binding (typing `w` goes to the filter); reserved-key sets differ between the two frontends.
**Info-2. Double render on `KEY_RESIZE`** (`tui.py:523-524` renders, then `handle_key` renders again) — harmless with curses, wasteful, pre-existing.
**Info-3. Repo hygiene** — the third-party review HTMLs live in the repo root (`CODE-REVIEW.html` tracked, `CODE-REVIEW-v3.html` untracked). Move to `docs/` or gitignore.

---

## Re-audit of the third-party reports (v2/v3)

Since both reports fed this round's plan, their claims were independently re-verified. Summary of corrections that future rounds should carry forward:

1. **F1 (v3) / U-item (v2) — "Poller.stop() race, thread may never terminate" was a false positive in both reports.** `threading.Event.wait(30)` (`poller.py:66`) returns immediately when the event is set, so `stop()` wakes the loop instantly and `join(5)` succeeds. Worst case: `join` returns early while a refresh is mid-flight — the thread still terminates. Neither report checked stdlib semantics. **No code change needed** (none was made).
2. **N7 (v3) — "`_clear_for_key` mutates a list during iteration" was a false positive.** The code iterates `to_remove` (a comprehension-built copy) and removes from `active` (`alerts.py:123-127`) — element-skipping cannot occur. No change made.
3. **"58/58 tests" was stale in both reports** — the suite actually runs 70 tests (README was right). v3's test-related P3 items (unused test imports) were real, though.
4. **v3's delta bookkeeping was unreliable**: header said 14+6+12 = "30 items" (actually 32), section 5 said "10 unprocessed" vs "12" in its own verdict, and its cross-reference list used stale F-numbering not matching its own body.
5. **v3 dropped v2's most severe open item (U1: curses 5/6 keys blank) without acknowledging it** — it had in fact been fixed (mode dispatch at `tui.py` render) before this round. Delta-tracking gaps go unnoticed exactly this way.
6. **Dead-code claims needed test-awareness**: v3 called `read_state`/`write_state` "0 calls" — true in source, but `test_read_write_state` exercises them; deleting on the report's say-so would have broken the suite. Kept deliberately.

---

## Remaining debt from v3 (status ledger)

| v3 item | Status now |
|---|---|
| F1 Poller.stop race | **Closed as false positive** (Event.wait semantics; no bug) |
| F2 frontend error handling | ✅ Fixed |
| F3 HTTP 200 errors | ✅ Fixed (now 400) |
| F4 handle_key logic | ✅ Fixed |
| N1 _validate_date ×3 | ✅ Fixed (utils single copy) |
| N2/N5/N8 unused imports & dead code | ✅ Fixed (AST scan clean except intentional re-exports) |
| N3 COMMANDS.md syntax | ✅ Fixed |
| N4 --force semantics | ✅ Fixed (bypass_cache; narrow effect documented as P2-4) |
| N6 SSE dead endpoint | ✅ Deleted per owner decision |
| N7 _clear_for_key | **Closed as false positive** |
| N9 non-today-date silent fallback | ✅ Fixed |
| N10 pyproject/CI | ⏸ Deferred (owner decision) |
| N11 SSE exception handling | ✅ Moot (SSE deleted) |
| N12 log() timestamp | ✅ Fixed |
| N13 CLI truncation | ✅ Fixed |
| Alerts history unbounded | ⏸ Open (P2-2) |
| --no-color / NO_COLOR | ⏸ Open (P3-6) |

---

## Recommended next round (by ROI)

1. **Add the missing regression tests** (P2-1) — API error semantics, bypass_cache, poller stop, one live-server smoke. Highest value: it locks in everything this round fixed.
2. **Cap alert history at 500** (P2-2) — 3 lines, removes unbounded growth.
3. **`pyproject.toml` + GitHub Actions (unittest + ruff)** (P2-3) — makes the suite a continuous fact instead of a remembered ritual; ruff will also sweep the P3 import leftovers in one pass.
4. **Decide `--force`'s promise** (P2-4) — wire it into the poller fallback or rescope the help text.
5. **Web UI polish** — populate or delete the dead `alert-banner`; add date/status controls or fix SPEC §6.3.
6. **`--no-color` / `NO_COLOR`** (P3-6) and housekeeping (move review HTMLs to `docs/`).

---

## Overall assessment

The project went from "two divergent implementations with a broken test suite" (v1 baseline) to a single-package, locally-bound, escaped-UI, 70-test-green codebase in three rounds. The remediation round specifically avoided the two trap findings (F1, N7) that a less skeptical reviewer would have "fixed", and every behavior change was verified live rather than assumed. The dominant remaining risk is no longer code quality — it is that **nothing guards the fixes**: no CI, no lint, no tests on web/poller. Round 5 should be a tooling round, not another cleanup round.

*Method notes: Python 3.11.9 on win32; verification commands: `python -m unittest test_hkg_flight` (70/70 OK, 0.15s), `py_compile` over all sources, AST import/dead-code scan, urllib smoke against a live `WebServer` on 127.0.0.1:8232, cache-persistence check for `bypass_cache`. All numbers in this report were re-derived from the working tree, not copied from prior reports.*
