"""env.toml's [cics]: the region served over TN3270, its first transaction, where it listens, and its clock."""

from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

from cics.dat_form import DatForm
from cics.region_clock import LOCAL_CLOCK, RegionClock
from pydantic import BaseModel, ConfigDict

_LOOPBACK = "127.0.0.1"
_TN3270 = 3270
_UNNAMED_ZONE = ZoneInfo("UTC")


class CicsRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_transid: str = ""
    host: str = _LOOPBACK
    port: int = _TN3270
    timezone: ZoneInfo = _UNNAMED_ZONE
    datform: DatForm = DatForm.MMDDYY

    def clock(self) -> RegionClock:
        if "timezone" not in self.model_fields_set:
            return RegionClock(now=LOCAL_CLOCK.now, datform=self.datform)
        return RegionClock(
            now=partial(datetime.now, self.timezone), datform=self.datform
        )
