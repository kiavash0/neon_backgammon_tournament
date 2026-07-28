# Architecture Decision Record

Every deviation from `NEON_BACKGAMMON_SPEC.md` is logged here with reasoning, per the spec's own instruction (§14, "Instructions to the implementing model", item 5).

## ADR-001: StorageBackend interface is synchronous, not async

**Phase:** A3
**Spec reference:** §3 ("Storage behind a repository interface"), §6.1 (SQLite/h5py demo backends)

**Decision:** `StorageBackend` (server/app/storage/base.py) exposes plain synchronous methods, guarded internally by `threading.Lock`, rather than `async def` methods guarded by `asyncio.Lock` as the spec's h5py note implies.

**Why:** At Phase A / demo scale, both backends (SQLite via stdlib `sqlite3`, h5py) are synchronous C-extension libraries with no async drivers in the standard toolchain. Making the interface `async def` while every implementation immediately blocks on a sync call would be a no-op wrapper — it adds `pytest-asyncio` as a dependency and complicates every call site without changing actual concurrency behavior (FastAPI still needs to offload blocking calls to a threadpool either way for sync work).

**How to apply:** Route handlers (Phase A4+) call storage methods directly or via `starlette.concurrency.run_in_threadpool` if a request path is hot enough to matter at demo scale. When Phase B1 migrates to PostgreSQL, the natural driver is `asyncpg`/SQLAlchemy's async engine — at that point `StorageBackend` should become `async def` in lockstep with the new backend, and this decision should be marked superseded.

## ADR-002: Room fill-timeout/downgrade and real seating-collision detection deferred out of A5

**Phase:** A5
**Spec reference:** §5.1 (fill-timeout + downgrade for large rooms; same-device/IP seating collision rule), §10.2 (fraud-seating gate)

**Decision:** A5 ships the room pools, join/leave, auto-replenish, and the lobby WebSocket channel, plus the `FRAUD_SEATING_CHECK` env-gated mode and its production/payout boot-refusal rail (§10.2's own explicit test requirement). It does **not** implement: (a) the `ROOM_FILL_TIMEOUT` cancel/downgrade behavior for large rooms, or (b) actual same-device/same-IP seating collision detection.

**Why:** (a) Downgrading a stalled room into a smaller tournament is tournament-manager behavior — it doesn't make sense to build before the tournament manager (A7) exists to act on it. (b) Real collision detection needs device-fingerprint/IP signal that isn't collected anywhere in the stack yet (that infrastructure arrives with mobile/attestation work, §8.3/B4); building a "check" with no real signal to check against would be a fake implementation, not a deferred one.

**How to apply:** Build (a) alongside the A7 tournament manager, where FULL rooms actually transition into running tournaments. Build (b) once device/IP signal exists on requests (likely alongside mobile client work or the dedicated B4 anti-fraud pass) — at that point, wire it into `app/lobby/service.join_room` behind the existing `FRAUD_SEATING_CHECK` mode, which is already fully wired and tested.

## ADR-003: A6 match play precedes tournament brackets; matches are hand-created until A7

**Phase:** A6
**Spec reference:** §14 roadmap (A6 before A7), §4.4, §6.3

**Decision:** A6 implements match play over `/ws` — `match_ready`/`move`/`resign`, server dice + engine legality, persistence-after-every-move, turn timers, and disconnect/reconnect grace — against `Match` rows that already exist in storage. It does not wire room-fill → bracket generation → match creation; that pipeline is A7 (the tournament manager), which doesn't exist yet. The roadmap itself puts A6 before A7, so this is the spec's own intended order, not a scope cut — documented here so it's clear why there's no REST path to create a match yet, only `storage.create_match` (used directly by tests and by the live-verification script for this phase).

**Also simplified within A6** (documented rather than silently dropped):

- **Reconnect timer pause is not capped at "once per player per game."** On disconnect, the active turn timer (if it was that player's turn) is cancelled and a full-duration timer restarts on reconnect. A player could in principle disconnect/reconnect repeatedly to keep resetting their own clock. Real-money implications are limited in Phase A (no prizes wired yet) — revisit if this becomes a griefing vector before real payouts.
- **Timeout/disconnect handling bypasses `legal_moves` client-membership validation by design** — these are server-issued moves (forced single option, or an explicit forfeit-turn skip), not client input, so they don't need the same trust boundary as `handle_move`.
- **`opponent_move` is only broadcast on client-submitted and timeout-forced moves**, not on the server's auto-skip when a player has zero legal moves at all (SPEC §4.3's "no legal move ⇒ auto-skip and notify") — the auto-skip currently updates state silently and the next real turn's `dice`/`state` messages carry the consequence forward. A dedicated `turn_skipped` notice would be a cheap follow-up if playtesting shows this is confusing on the client.

## ADR-004: A7 tournament manager — bracket/round-advance/crash-recovery shipped; fill-timeout/downgrade still deferred

**Phase:** A7
**Spec reference:** §5.1 (`ROOM_FILL_TIMEOUT` cancel/downgrade), §5.2 (bracket generation, round advancement, crash recovery), §5.3 (prize pool), §14 A7 DoD

**Decision:** A7 implements CSPRNG bracket seeding, round-by-round match creation with deterministic pairing (`Match.bracket_slot`), automatic round advancement on every match conclusion (bear-off, resign, any forfeit path), the stub ad-revenue/prize model, ledger credit, and crash recovery (`recover_tournaments`, run at every startup, idempotent). It still does **not** implement the `ROOM_FILL_TIMEOUT` cancel-or-downgrade behavior for large rooms that stall before filling — ADR-002 deferred this pending the tournament manager's existence; it now exists, but downgrade needs a periodic background scan (nothing stalls a room without external time passing — there's no in-request trigger for it the way match/tournament advancement has), which is a different kind of infrastructure (a scheduled job) than anything built so far.

**Why:** Building a one-off timer per room would duplicate the timer/grace patterns already established (turn timeouts, disconnect grace, join timeouts) but for a much longer horizon (hours/days per SPEC's `ROOM_FILL_TIMEOUT` example of 24h for ≥128), which isn't practical to keep alive as an in-memory `asyncio.sleep` task across restarts — it needs to be a real periodic scan job, a piece of infrastructure this phase hasn't needed yet.

**How to apply:** Build it as a periodic startup/cron-style task (candidate home: alongside `recover_tournaments` in the lifespan startup, or a proper scheduled job once Phase B introduces one) that scans `OPEN` rooms older than `ROOM_FILL_TIMEOUT`, and either cancels them (releasing registrants) or downgrades to the next-lower power-of-2 using the earliest joiners — both paths reuse `app.tournament.service.start_tournament`'s pattern directly.

**Also worth noting — verified live, not just unit-tested:** a real server process was hard-killed (`SIGKILL`) mid-tournament (one match finished, a second mid-turn) and restarted against the same SQLite file. This surfaced and fixed a real bug: `MatchRuntime.dice` only ever lived in memory, so a resumed mid-turn player got `your_turn: true` with `legal_moves: []` — an unplayable dead end. Fixed in `app.match.ws_handlers.handle_match_ready`: when a match is `RUNNING` but the runtime has no dice on record (fresh runtime — first ready ping, or a real restart), the server now re-rolls for the current turn instead of replaying a stale empty state. Regression test: `test_resume_after_process_restart_gets_playable_state` in `tests/test_match_ws.py`.

## ADR-005: A8 web client renders the interactive board as 2D SVG, not the 3D `.glb` assets

**Phase:** A8
**Spec reference:** §11 ("Provided neon-styled art assets will be supplied for boards/checkers/dice/UI chrome; build the demo with placeholder assets structured so final assets drop in")

**Decision:** The match board (`web/js/board.js`) is a precisely-coordinated 2D SVG board — standard backgammon point layout (SPEC §4.1 numbering: index *i* = point *i+1*, White home 0-5, Black home 18-23), styled with the neon dark theme. It does not render the provided `.glb` 3D models (boards/checkers/dice/carpets under `assets/models/`) as the interactive surface.

**Why:** The `.glb` files are art assets with no documented coordinate metadata — there's no reliable way to know where each of the 24 points, the bar, or the off-trays sit on a given model's geometry without opening it in a DCC tool and measuring. Guessing at a mapping risks a *silently wrong* board (checkers rendered in the wrong slot) that looks plausible but misleads a player — much worse than an honest, simple 2D board. A 2D SVG board has an exactly-known coordinate system, so click targets and rendered checker positions are always provably correct, and it made the progressive multi-die move-sequence interaction (click a checker, then a highlighted legal destination, repeating for doubles) straightforward to implement and to drive from an automated browser test.

**How to apply:** The asset manifest (`assets/manifest.json`) built during scaffolding already exists for exactly this drop-in-later purpose. A follow-up pass can either (a) render the `.glb` fullset as a decorative/theme-preview element (e.g. a rotating showcase on the lobby or a theme picker) without it being the interactive surface, or (b) do the real work of measuring each model's point coordinates and switching the interactive board to 3D — that's a deliberate, scoped task, not something to bolt on speculatively.

**Verified live (not just unit-tested):** Two isolated real Chrome browser contexts (via Playwright, driven from outside the test suite) signed up, joined the same 2-player room, and played a complete game to a bear-off win entirely through actual clicks on the rendered SVG board — no simulated WebSocket clients. This run caught a second real bug: `handle_move`/`_advance_turn`/`_on_turn_timeout` never sent a final `state` message on the winning move, so the client's last-rendered board froze one move short of the true final position (e.g. showing 14 off instead of 15). Fixed by having `_finish_and_broadcast` in `app/match/ws_handlers.py` accept an optional `final_state` and broadcast it before `match_result`. Regression test: the strengthened `test_full_game_over_two_websocket_clients` in `tests/test_match_ws.py` now asserts the last-seen `game_state` shows 15 off for one side.

**Post-ship UX bugs found via user report + live re-verification (three more real fixes):**

1. **Silent 30-second dead wait.** The `TOURNAMENT_GET_READY_SECONDS` countdown (SPEC §5.2) had zero client-side representation — the bracket screen just sat static on "Status: RUNNING" for the full 30s, which reads as broken, not "starting soon." Fixed: `tournament_start` now carries `get_ready_seconds`, and the bracket screen shows a live pulsing countdown ring (`web/js/app.js` `startCountdown`/`stopCountdown`, `web/index.html`/`style.css`).
2. **No feedback during a move's network round-trip.** Completing a move dims/disables the board (`.board-root.submitting`) until the next `state`/`dice`/`match_result` arrives, so a slow connection doesn't look like a dropped click. Barely visible on localhost (round-trip is near-instant there) — this exists for real network conditions.
3. *(Superseded by ADR-006 — the display-only fix below wasn't enough; the protocol itself was still batched.)* **The real bug behind "you buffer the moves and apply them all at once" (verbatim user report, reproduced with a double roll — 2-2 = 4 moves):** `board.js`'s progressive move-sequence picker correctly narrowed *legality* on each click, but never updated the rendered checker positions until the whole sequence was submitted and the server responded — so on a double, all 4 checkers appeared to jump simultaneously on the last click. Fixed by adding `Board.displayState` (a local copy of game state mutated by a JS mirror of the engine's atomic-move application, `_applyLocal`, on every single pick) and rendering from it instead of the last-server-confirmed `state` — each click now moves its checker immediately, independent of the server round-trip. Verified live: watched 56 real atomic-move clicks across a full game (including a caught `4-4` double) and confirmed the board updates on every click, not just the last one. Also fixed a related hit-testing bug this surfaced: the bar's click target (`_drawBar`) had no background shape when empty, so clicks could be intercepted by the bar's background rect instead of registering — added an always-present transparent hit-area rect, matching how points (triangle) and the off-tray (rect) already worked.

## ADR-006: Per-die move submission — atomic moves are independent protocol events, not an end-of-turn batch

**Phase:** A8 follow-up (second user report: fixing only the mover's local display was insufficient)
**Spec reference:** §6.3 (WS protocol `move {mid, seq}`), §4.3 (each die is a separate move)

**Decision:** The `move` WS message now accepts a *partial* sequence (typically one atomic move per message). The server validates each submission as a prefix of some legal sequence for the current dice (`runtime.turn_prefix` accumulates the turn's committed moves in memory), pushes each atomic move to the opponent immediately as its own `opponent_move` message, and only applies/persists/advances the turn once the accumulated sequence has no legal continuation. Full-sequence submissions still work unchanged (a complete sequence is its own prefix), so all prior tests pass without modification. The client submits every pick the moment it happens and renders `opponent_move` pushes live on the waiting player's board (`Board.applyRemote`).

**Why:** The previous protocol forced the client to buffer the whole turn and submit it at once — so the opponent watched nothing happen and then saw 2–4 checkers teleport simultaneously. The user's report was explicit: each move must happen independently as it's clicked, on both boards.

**Consequences / edge handling:**
- Nothing is persisted mid-turn; the stored game state is always the turn-start state, so crash/reconnect semantics stay simple: a mid-prefix disconnect or re-`match_ready` restarts the turn from its start (prefix dropped, full options resent). An opponent who reconnects mid-prefix briefly sees the turn-start board until the authoritative post-turn state arrives — logged as acceptable demo-scale drift.
- Turn timeout with a non-empty prefix completes the turn with the first legal continuation (rather than snapping already-visible moves back off the board), and the opponent is sent only the suffix they haven't already seen.
- Doubles now display as four dice in the client, matching their four-move reality (SPEC §4.2).

**Verified:** deterministic server test (`test_moves_can_be_submitted_one_die_at_a_time`) asserts each atomic move arrives at the opponent as its own `opponent_move` *before* any turn-advancing state, and that the turn advances only after the final one; plus live two-browser verification — across multi-move turns including three caught doubles (6-6, 5-5, 2-2), the waiting player's board visibly updated after each individual click of the mover (50/52 mid-turn checks registered within the 250ms polling window).
