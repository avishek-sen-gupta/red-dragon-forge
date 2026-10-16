"""The names of a package's zip entries, shared by build and open."""

MANIFEST_ENTRY = "manifest.json"
IMAGE_ENTRY = "image.linked.json"


def mapset_entry(mapset: str) -> str:
    return f"maps/{mapset}.json"
