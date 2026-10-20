"""The region's clock: the local time ASKTIME reads, and the DATFORM FORMATTIME DATE follows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from cics.dat_form import DatForm


def _machine_local_now() -> datetime:
    return datetime.now().astimezone()


@dataclass(frozen=True)
class RegionClock:
    now: Callable[[], datetime]
    datform: DatForm


LOCAL_CLOCK = RegionClock(now=_machine_local_now, datform=DatForm.MMDDYY)
