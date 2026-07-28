import os

from app.storage.base import StorageBackend


def get_storage_backend(
    backend: str | None = None, path: str | None = None
) -> StorageBackend:
    """Build the configured StorageBackend. Reads STORAGE_BACKEND / STORAGE_PATH
    from the environment when not passed explicitly (SPEC §3: backend
    selection is a config flag, never a hardcoded choice).
    """
    backend = (backend or os.environ.get("STORAGE_BACKEND", "sqlite")).lower()
    # Default to a real file, not ":memory:" — `make dev` runs uvicorn with
    # --reload, and an in-memory DB silently wipes every account/room on every
    # code change, leaving browsers holding tokens for users that no longer
    # exist. Tests always pass an explicit ":memory:" path.
    path = path if path is not None else os.environ.get("STORAGE_PATH", "./dev.sqlite3")

    if backend == "sqlite":
        from app.storage.sqlite_backend import SqliteBackend

        return SqliteBackend(path)
    if backend == "h5":
        from app.storage.h5_backend import H5Backend

        return H5Backend(path)

    raise ValueError(f"Unknown STORAGE_BACKEND: {backend!r} (expected 'sqlite' or 'h5')")
