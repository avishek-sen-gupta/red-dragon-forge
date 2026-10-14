"""Reading a fixed-length-record flat file: a cataloged dataset's bytes as its records."""

from __future__ import annotations

from pathlib import Path


def read_flat_file(path: Path, record_length: int) -> list[bytes]:
    """Read a flat file as a list of fixed-length records.

    A missing file yields []. Raises ValueError if the file size is not a
    multiple of record_length (corrupt / wrong record length).
    """
    if not path.exists():
        return []
    data = path.read_bytes()
    if record_length <= 0:
        raise ValueError(f"record_length must be positive, got {record_length}")
    if len(data) % record_length != 0:
        raise ValueError(
            f"{path}: size {len(data)} is not a multiple of record_length "
            f"{record_length}"
        )
    return [data[i : i + record_length] for i in range(0, len(data), record_length)]
