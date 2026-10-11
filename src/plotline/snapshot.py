"""Start-up integrity check of the frozen snapshot (data contract section 6)."""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_snapshot(csv_path: Path, hash_path: Path) -> tuple[str, str | None]:
    """Return (actual sha256, error message or None). A mismatch is a domain
    error (``E_SNAPSHOT_HASH``), so it is returned, not raised."""
    actual = compute_sha256(csv_path)
    expected = hash_path.read_text().strip().split()[0].lower()
    if actual != expected:
        return actual, f"snapshot sha256 {actual} does not match {hash_path.name} ({expected})"
    return actual, None
