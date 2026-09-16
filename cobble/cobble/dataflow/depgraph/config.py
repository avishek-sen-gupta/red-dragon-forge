"""config.py — the depgraph target's configuration, from a TOML file.

Nothing about a corpus is hardcoded in build.py: which ASG cache to read, where
the graph goes, and which names the collapse is allowed to route through all come
from here.

Own file rather than a section of the corpus TOML, because the pass-through set is
not a fact about the corpus. It is a JUDGMENT, revised once per round of the loop
(build, read the CONDUIT CANDIDATES table, add the names that are conduits,
build again), so it changes on a different clock from cobol_dir.

No [source] section, and deliberately: which programs were parsed, which copybook
directories resolved their COPY statements and which bridge JAR did the work are
facts about the PARSE, and they live in the corpus config the parse reads. Repeating them here would let two configs disagree about which corpus this
asg_dir holds, and the graph would then describe members nobody parsed.

Shape:

    [output]
    asg_dir = "out-parsed"       # the directory cobble-parse-corpus wrote
    graph_dir = "out-depgraph"

    [collapse]
    window = 1
    passthrough_names = ["WS-NUMERIAL"]
    passthrough_patterns = ["^WS-EDIT($|-)"]

Every key without a default is read through _require, so a missing one raises
instead of silently guessing a path -- the same rule corpus_config.py follows.
Relative paths stay relative to the caller's working directory, also as there.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# How many MOVEs apart A -> B and B -> C may be and still collapse through a
# pass-through B. 1 means immediately consecutive, which is what "right next to
# each other" means and what stops the collapse from inventing pairings.
DEFAULT_COLLAPSE_WINDOW = 1


@dataclass(frozen=True)
class DepgraphConfig:
    asg_dir: Path
    graph_dir: Path
    passthrough_names: tuple[str, ...] = ()
    passthrough_patterns: tuple[str, ...] = ()
    collapse_window: int = DEFAULT_COLLAPSE_WINDOW


def _require(data: Mapping, key: str) -> object:
    if key not in data:
        raise KeyError(f"depgraph config missing required key: {key!r}")
    return data[key]


def depgraph_config_from_dict(data: Mapping) -> DepgraphConfig:
    """The pure half: parsed TOML -> DepgraphConfig, no I/O."""
    output = _require(data, "output")
    # An absent [collapse] is round 1 of the loop: literal connectivity, nothing
    # collapsed. That is a legitimate way to run this, so it is not an error.
    collapse: Mapping = data.get("collapse", {})
    return DepgraphConfig(
        asg_dir=Path(_require(output, "asg_dir")),
        graph_dir=Path(_require(output, "graph_dir")),
        passthrough_names=tuple(collapse.get("passthrough_names", ())),
        passthrough_patterns=tuple(collapse.get("passthrough_patterns", ())),
        collapse_window=int(collapse.get("window", DEFAULT_COLLAPSE_WINDOW)),
    )


def load_depgraph_config(path: Path) -> DepgraphConfig:
    return depgraph_config_from_dict(tomllib.loads(path.read_text()))
