"""The names of a package's zip entries, shared by build and open."""

MANIFEST_ENTRY = "manifest.json"


def program_entry(program: str) -> str:
    return f"programs/{program}.linked.json"


def mapset_entry(mapset: str) -> str:
    return f"maps/{mapset}.json"
