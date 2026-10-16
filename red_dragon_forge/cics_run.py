"""env.toml's [cics]: the region served over TN3270, its first transaction and where it listens."""

from pydantic import BaseModel, ConfigDict

_LOOPBACK = "127.0.0.1"
_TN3270 = 3270


class CicsRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_transid: str = ""
    host: str = _LOOPBACK
    port: int = _TN3270
