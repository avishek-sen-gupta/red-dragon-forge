"""A seed a reachability walk cannot start from."""


class ReachError(ValueError):
    """Named so a caller can report why, before any row is written."""
