"""env.toml's [plain]: one program entered directly, its ASSIGN names bound to cataloged datasets."""

from collections.abc import Mapping

from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from pydantic import BaseModel, ConfigDict


class PlainRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str
    max_steps: int = DEFAULT_PROGRAM_STEP_BUDGET
    files: Mapping[str, str] = {}
