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
