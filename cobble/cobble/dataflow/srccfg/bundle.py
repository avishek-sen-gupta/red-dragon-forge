"""The one shape a CFG file has, and the only code that reads or writes it.

    {"cfgs": [ ...one dict per program... ], "calls": [ ...what joins them... ]}

Every writer emits exactly this, and every reader accepts exactly this. A corpus
member is a one-element ``cfgs`` with no ``calls``; a closure of one program is the
same file. Neither a missing key nor an empty list is a different shape: absence is
spelled ``[]``, so no reader has to ask which kind of file it was handed.

It was once three shapes -- a bare object per corpus member, a bare list from the
closure CLI, and this object once ``calls`` existed. Every reader then carried its
own guess at which it had, and the guesses disagreed: ``accesses`` iterated a dict's
keys and crashed, ``load_cfg`` handed back a Cfg with no program and no nodes, and a
one-program bundle could not be told from a bare object at all, so its calls were
silently dropped. The shapes are gone rather than tolerated, because a reader that
accepts three cannot tell a stale file from a current one.

Files written before this are not read. ``cobble-srccfg-build`` regenerates them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from cobble.dataflow.srccfg.cfg import (
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    SourceSpan,
)
from cobble.dataflow.srccfg.link import BundleCall

JsonValue = str | int | float | bool | Sequence["JsonValue"] | Mapping[str, "JsonValue"]

BUNDLE_CFGS = "cfgs"
BUNDLE_CALLS = "calls"

REBUILD_HINT = "rebuild it with cobble-srccfg-build"


class CfgDocumentError(ValueError):
    """A CFG file that is not in the one shape, named so a caller can say which."""


@dataclass(frozen=True)
class Bundle:
    seed: str
    cfgs: tuple[Cfg, ...] = ()
    calls: tuple[BundleCall, ...] = ()


def cfg_to_dict(cfg: Cfg) -> dict:
    """Plain JSON: enum members become their names, so a reader needs no import of
    this package to interpret an edge."""
    return {
        "program": cfg.program,
        "nodes": [_node_dict(node) for node in cfg.nodes],
        "edges": [
            {"source": e.source, "target": e.target, "kind": e.kind.name}
            for e in cfg.edges
        ],
    }


def _node_dict(node: Node) -> dict:
    return {**asdict(node), "kind": node.kind.name}


def cfg_from_dict(document: Mapping) -> Cfg:
    return Cfg(
        program=str(document.get("program", "")),
        nodes=tuple(_node_of(entry) for entry in document.get("nodes", ())),
        edges=tuple(
            Edge(source=e["source"], target=e["target"], kind=EdgeKind[e["kind"]])
            for e in document.get("edges", ())
        ),
    )


def _node_of(entry: Mapping) -> Node:
    atom = entry.get("atom", {})
    span = entry.get("span", {})
    return Node(
        **{
            **{
                k: v
                for k, v in entry.items()
                if k not in ("kind", "atom", "span", "writes", "reads", "using")
            },
            "kind": NodeKind[entry["kind"]],
            "atom": Atom(**atom),
            "span": SourceSpan(**span) if span else SourceSpan(),
            "writes": tuple(entry.get("writes", ())),
            "reads": tuple(entry.get("reads", ())),
            "using": tuple(entry.get("using", ())),
        }
    )


def bundle_to_json(bundle: Bundle) -> str:
    """The seed's CFG first, then its callees': an ordered list, because the order is
    the answer's, inside an object, because the calls belong to the bundle and not to
    any one of its programs."""
    return json.dumps(
        {
            BUNDLE_CFGS: [cfg_to_dict(cfg) for cfg in bundle.cfgs],
            BUNDLE_CALLS: [asdict(call) for call in bundle.calls],
        }
    )


def one_cfg_document(cfg: Cfg) -> str:
    """A single program written in the shape every reader expects: one CFG, no calls."""
    return bundle_to_json(Bundle(seed=cfg.program, cfgs=(cfg,)))


_BARE_LIST = f"a bare list of CFGs is the pre-{BUNDLE_CFGS} shape and is no longer read"
_BARE_CFG = (
    f"no {BUNDLE_CFGS!r} key; a bare CFG object is the pre-{BUNDLE_CFGS} shape "
    "and is no longer read"
)
_NOT_A_DOCUMENT = "not a CFG document"


def _refused(source: str, problem: str) -> CfgDocumentError:
    return CfgDocumentError(f"{source}: {problem} -- {REBUILD_HINT}")


def _with_cfgs(document: Mapping, source: str) -> Mapping:
    if BUNDLE_CFGS in document:
        return document
    raise _refused(source, _BARE_CFG)


def _shape_of(document: JsonValue, source: str) -> Mapping:
    """The document, or a refusal naming the shape it is instead."""
    if isinstance(document, Mapping):
        return _with_cfgs(document, source)
    raise _refused(
        source, _BARE_LIST if isinstance(document, list) else _NOT_A_DOCUMENT
    )


def cfg_dicts_of(
    document: JsonValue, source: str = "<document>"
) -> tuple[Mapping, ...]:
    """The CFG objects as written, for the readers that want JSON rather than a Cfg."""
    return tuple(_shape_of(document, source)[BUNDLE_CFGS])


def calls_of(document: JsonValue, source: str = "<document>") -> tuple[BundleCall, ...]:
    """The calls that join the CFGs; a file with none spells that ``[]``."""
    return tuple(
        BundleCall(**entry)
        for entry in _shape_of(document, source).get(BUNDLE_CALLS, ())
    )


def bundle_of(document: JsonValue, source: str = "<document>") -> Bundle:
    cfgs = tuple(cfg_from_dict(entry) for entry in cfg_dicts_of(document, source))
    return Bundle(
        seed=cfgs[0].program if cfgs else "",
        cfgs=cfgs,
        calls=calls_of(document, source),
    )


def load_document(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(path: Path) -> Bundle:
    return bundle_of(load_document(path), str(path))


def load_cfg_dicts(path: Path) -> tuple[Mapping, ...]:
    """The CFG objects in a file, for a reader that walks the JSON directly."""
    return cfg_dicts_of(load_document(path), str(path))
