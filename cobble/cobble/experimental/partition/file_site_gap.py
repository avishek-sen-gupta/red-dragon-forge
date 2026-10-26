"""Why a file site resolved to no dataset, the first of these that holds."""

from __future__ import annotations

from enum import StrEnum


class FileSiteGap(StrEnum):
    """Its key is a target of another kind; its program has file targets at other nodes; its program has SELECTs under other names; its program has only non-file targets; or its program is in neither table."""

    TARGET_NOT_FILE = "target-not-file"
    FILE_TARGETS_AT_OTHER_NODES = "file-targets-at-other-nodes"
    SELECTS_UNDER_OTHER_NAMES = "selects-under-other-names"
    ONLY_NON_FILE_TARGETS = "only-non-file-targets"
    PROGRAM_UNKNOWN = "program-unknown"
