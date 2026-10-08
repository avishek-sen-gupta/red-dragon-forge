"""A log line prefixed with how long its process has been running."""

from __future__ import annotations

import logging

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600


class ElapsedFormatter(logging.Formatter):
    """``[1h02m03s] message``: the time since the process started logging, from the
    record itself, so a run on another machine says how long it has waited at
    every line rather than only at the end."""

    def format(self, record: logging.LogRecord) -> str:
        total = int(record.relativeCreated // 1000)
        hours, rest = divmod(total, _SECONDS_PER_HOUR)
        minutes, seconds = divmod(rest, _SECONDS_PER_MINUTE)
        return f"[{hours}h{minutes:02d}m{seconds:02d}s] {super().format(record)}"
