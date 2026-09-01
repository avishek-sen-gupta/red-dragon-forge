"""cli_logging.py — the logging configuration cobble's entry points share.

Every module under cobble/ reports through ``logging.getLogger(__name__)``; what
differs between a library and an entry point is who is allowed to configure the
root logger. That is this module's only job, so the six scripts do not each carry
their own copy of the same three arguments.

Two choices worth stating, because both are deliberate rather than default:

  - Message-only format. These summaries are bracketed, multi-line reports meant
    for whoever is watching a corpus build; an 'INFO:cobble.build_graph:' on all
    twenty lines of one makes it unreadable. The cost is that severity no longer
    shows in the output, so the warnings cobble raises mark themselves with '!!'.
  - stderr. The tqdm progress bars are already there, so a per-stage count and
    the bar it followed interleave in the order they happened; and it leaves
    stdout for the one thing that is machine-readable, cobble.diagnosis' JSON.

basicConfig is a no-op when the root logger already has a handler, which is what
makes this safe to call from a main() that pytest is driving: the test harness's
own capture stays in place and caplog still sees every record.
"""

from __future__ import annotations

import logging
import sys


def configure_cli_logging(level: int = logging.INFO) -> None:
    """Configure the root logger for a console entry point.

    Call this from main() and nowhere else -- a library that configures logging
    takes the choice away from the program importing it.
    """
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr)
