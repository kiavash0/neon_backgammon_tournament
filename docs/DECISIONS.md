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
