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
    path = path if path is not None else os.environ.get("STORAGE_PATH", ":memory:")

    if backend == "sqlite":
        from app.storage.sqlite_backend import SqliteBackend

        return SqliteBackend(path)
    if backend == "h5":
        from app.storage.h5_backend import H5Backend

        return H5Backend(path)

    raise ValueError(f"Unknown STORAGE_BACKEND: {backend!r} (expected 'sqlite' or 'h5')")
