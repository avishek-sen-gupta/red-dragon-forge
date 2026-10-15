"""A Pydantic validation failure as one line: each error's location and message."""

from pydantic import ValidationError


def validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
        for detail in error.errors()
    )
