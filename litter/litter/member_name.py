"""A z/OS member name: 1-8 characters, the first A-Z, # @ or $, the rest those or 0-9."""

from typing import Annotated

from pydantic import StringConstraints

MemberName = Annotated[str, StringConstraints(pattern=r"^[A-Z#@$][A-Z0-9#@$]{0,7}$")]
