"""expanded_cache.py — the naming rule for a corpus's expanded source.

The same rule asg_cache.py uses, and for the same reason: the name is a pure
function of the source FILENAME, so a member's expansion is found from the
member's path alone. MYPROG01.txt becomes MYPROG01.cbl.

`.cbl` rather than an extension of its own because the file IS COBOL -- the text
the ANTLR lexer was handed. An expanded member can be fed straight back to the
bridge with no copybook directories configured, which is how a member that will
not parse gets narrowed down to the line that breaks it.

Failures reuse asg_cache's `.fail` record verbatim. A member that will not expand
will not expand on the next run either, and the reason is the same one: the copy
book is absent until somebody stages it.
"""

from __future__ import annotations

from pathlib import Path

from cobble.parsing.asg_cache import failure_path


def expanded_path(out_dir: Path, source: Path) -> Path:
    return out_dir / f"{source.stem}.cbl"


def is_expanded(out_dir: Path, source: Path) -> bool:
    """Whether this member has been through the preprocessor, either way."""
    return (
        expanded_path(out_dir, source).exists()
        or failure_path(out_dir, source).exists()
    )
