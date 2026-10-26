"""env.toml's [plain]: one program entered directly, its ASSIGN names bound to cataloged datasets."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

DEFAULT_PLAIN_STEP_BUDGET = 500_000


class PlainRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str
    max_steps: int = DEFAULT_PLAIN_STEP_BUDGET
    files: Mapping[str, str] = {}
