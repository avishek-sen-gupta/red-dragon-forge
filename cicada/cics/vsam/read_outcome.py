"""What a CICS READ, READNEXT or READPREV gives back: a record, or the condition instead of one."""

from __future__ import annotations

from typing import TypeAlias

from cics.vsam.no_record import NoRecord
from cics.vsam.record_read import RecordRead

ReadOutcome: TypeAlias = RecordRead | NoRecord
