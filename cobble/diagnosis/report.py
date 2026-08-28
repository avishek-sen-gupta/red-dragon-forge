"""What every diagnosis does the same way: label a member, place the JSON.

Extracted at the third diagnostic rather than the second. Two copies of a dozen
lines is a coincidence; three is a convention, and a convention that lives in one
place cannot drift -- which matters here because both halves of it are the channel
split the package docstring promises, not formatting.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger(__name__)

RULE = "=" * 78


def member_label(path: Path, seen: Mapping[str, int]) -> str:
    """The filename alone, or ``<library>/<filename>`` when two libraries hold a
    member of that name.

    A report exists to say which file to open, and the full path would put a corpus
    directory into the JSON for no gain -- the config that produced the run already
    says which directories were walked.

    ``seen`` counts filenames across the members being reported, so the qualifier
    appears only where it is needed to tell two of them apart.
    """
    if seen[path.name] == 1:
        return path.name
    return f"{path.parent.name}/{path.name}"


def emit_json(payload: str, args: argparse.Namespace) -> None:
    """--output if it was given, stdout otherwise.

    Takes the parsed args rather than an optional path so that "no --output" stays
    argparse's absent-flag default and does not become a None threaded through
    every caller's signatures.
    """
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
        # Only the path, never the contents: those are the corpus's own identifiers.
        logger.info("Wrote %s", args.output)
    else:
        # Written, not logged: this is the machine channel. A log record would put
        # the JSON on stderr behind whatever prefix the handler adds, and `| jq`
        # would get nothing.
        sys.stdout.write(payload + "\n")
