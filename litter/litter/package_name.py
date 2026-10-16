"""A package's name: the zip's stem, letters, digits, '_', '-' or '.', never a path."""

from typing import Annotated

from pydantic import StringConstraints

PackageName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
