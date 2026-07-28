# Architecture Decision Record

Every deviation from `NEON_BACKGAMMON_SPEC.md` is logged here with reasoning, per the spec's own instruction (§14, "Instructions to the implementing model", item 5).

## ADR-001: StorageBackend interface is synchronous, not async

**Phase:** A3
**Spec reference:** §3 ("Storage behind a repository interface"), §6.1 (SQLite/h5py demo backends)

**Decision:** `StorageBackend` (server/app/storage/base.py) exposes plain synchronous methods, guarded internally by `threading.Lock`, rather than `async def` methods guarded by `asyncio.Lock` as the spec's h5py note implies.

**Why:** At Phase A / demo scale, both backends (SQLite via stdlib `sqlite3`, h5py) are synchronous C-extension libraries with no async drivers in the standard toolchain. Making the interface `async def` while every implementation immediately blocks on a sync call would be a no-op wrapper — it adds `pytest-asyncio` as a dependency and complicates every call site without changing actual concurrency behavior (FastAPI still needs to offload blocking calls to a threadpool either way for sync work).

**How to apply:** Route handlers (Phase A4+) call storage methods directly or via `starlette.concurrency.run_in_threadpool` if a request path is hot enough to matter at demo scale. When Phase B1 migrates to PostgreSQL, the natural driver is `asyncpg`/SQLAlchemy's async engine — at that point `StorageBackend` should become `async def` in lockstep with the new backend, and this decision should be marked superseded.
