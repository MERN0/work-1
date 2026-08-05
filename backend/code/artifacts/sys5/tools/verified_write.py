"""Verified write: write bytes to disk, then read them back and confirm the
SHA-256 hash and byte count match before declaring success. This was a real
failure mode in the previous SYS5 build (silent truncated/corrupted writes),
so every output workbook goes through this instead of a bare .save()/write().
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from logging_setup import get_logger

log = get_logger("verified_write")


class VerifiedWriteError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path`, then read it back and verify byte-for-byte."""
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_hash = _sha256(data)
    expected_len = len(data)

    log.info("Writing %s (%d bytes)", path, expected_len)
    path.write_bytes(data)

    actual = path.read_bytes()
    actual_hash = _sha256(actual)

    if len(actual) != expected_len or actual_hash != expected_hash:
        log.error(
            "Verified write FAILED for %s: expected %d bytes / sha256=%s, got %d bytes / sha256=%s",
            path, expected_len, expected_hash, len(actual), actual_hash,
        )
        raise VerifiedWriteError(f"Verified write failed for {path}")

    log.info("Verified write OK: %s (sha256=%s, %d bytes)", path, expected_hash, expected_len)


def verified_write_workbook(path: Path, workbook) -> None:
    """Save an openpyxl Workbook via an in-memory buffer, then verified-write
    the resulting bytes so we check the actual serialized output, not just
    that .save() didn't raise."""
    import io

    buf = io.BytesIO()
    workbook.save(buf)
    verified_write_bytes(path, buf.getvalue())
