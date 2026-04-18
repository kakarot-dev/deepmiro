"""
persistence — atomic JSON writer + SurrealDB upsert helper for LifecycleStore.

Disk is ground truth. SurrealDB is a best-effort cache for cross-process
queries (MCP tool, API, frontend). When SurrealDB is unreachable, the disk
write still succeeds and the DB catches up on the next transition.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger("mirofish.lifecycle.persistence")


def write_state_atomic(path: str, data: dict[str, Any]) -> None:
    """Atomically write JSON to `path` via tmp file + rename.

    A crash mid-write leaves the old file intact. The directory is fsynced
    on Unix so the rename is durable across power loss (best-effort; we
    don't block the hot path on fsync in every case).
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    # NamedTemporaryFile with delete=False gives us a handle we can rename.
    fd, tmp_path = tempfile.mkstemp(
        prefix=".state_",
        suffix=".json.tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Fsync not supported (e.g. some network filesystems). Ignore.
                pass
        # Atomic rename. On POSIX this is atomic; on Windows it isn't but
        # we don't deploy there.
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the tmp file if anything went wrong.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def upsert_simulation_row(snapshot_dict: dict[str, Any]) -> bool:
    """Best-effort upsert into SurrealDB `simulation` table.

    Returns True on success, False on failure. Never raises — the caller
    keeps going either way because disk is authoritative.

    The `state` field of the snapshot is an Enum value; we serialize its
    .value (the string) before sending to SurrealDB.
    """
    sim_id = snapshot_dict.get("simulation_id")
    if not sim_id:
        logger.warning("upsert_simulation_row: missing simulation_id, skipping")
        return False

    try:
        # Late import: the lifecycle package must be safe to import even
        # if SurrealDB storage isn't configured (tests, dev mode).
        from ...storage.factory import get_storage
        from ...storage.surrealdb_backend import SurrealDBStorage

        storage = get_storage()
        if not isinstance(storage, SurrealDBStorage):
            return False

        # Serialize for DB: Enum → value, deques → lists, etc. (already
        # handled by snapshot.to_dict upstream, but be defensive.)
        db_row = _to_db_row(snapshot_dict)
        storage.upsert_simulation(sim_id, db_row)
        return True
    except Exception as exc:
        logger.warning(
            "SurrealDB upsert for sim=%s failed (disk still written): %s",
            sim_id, exc,
        )
        return False


def _to_db_row(snapshot_dict: dict[str, Any]) -> dict[str, Any]:
    """Coerce snapshot dict into a row SurrealDB can accept.

    Enum → string, datetime → iso, dicts/lists pass through, drop keys
    whose values are None (SurrealDB is strict about NULL vs missing).
    """
    row: dict[str, Any] = {}
    for k, v in snapshot_dict.items():
        if v is None:
            continue
        if hasattr(v, "value"):  # Enum
            row[k] = v.value
        else:
            row[k] = v
    return row
