"""The closure bundle and the file it is written to.

    {"cfgs": [ ...one dict per program... ], "calls": [ ...what joins them... ]}

The CFGs are unchanged, because they are also written one per file by the corpus
build and nothing about that changed. The calls are what the file used to make every
reader re-derive: a call site, and the entry node in the callee it lands on, which is
the one thing a CallSite does not carry and exactly what a traversal needs.

Reading is the other direction and takes three shapes, since a per-member CFG file
and a bundle written before this key existed are both still files a person has on
disk. Both load as a bundle with no calls, and a reader with no calls derives them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import (
    BUNDLE_CFGS,
    cfg_to_dict,
    cfgs_of,
    load_document,
)
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.link import BundleCall

BUNDLE_CALLS = "calls"


@dataclass(frozen=True)
class Bundle:
    seed: str
    cfgs: tuple[Cfg, ...] = ()
    calls: tuple[BundleCall, ...] = ()


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


def calls_of(document) -> tuple[BundleCall, ...]:
    """The bundle's calls, empty for the two shapes that never carried any."""
    if isinstance(document, list) or BUNDLE_CALLS not in document:
        return ()
    return tuple(_call_of(entry) for entry in document[BUNDLE_CALLS])


def _call_of(entry: Mapping) -> BundleCall:
    return BundleCall(**entry)


def bundle_of(document) -> Bundle:
    cfgs = cfgs_of(document)
    return Bundle(
        seed=cfgs[0].program if cfgs else "",
        cfgs=cfgs,
        calls=calls_of(document),
    )


def load_bundle(path: Path) -> Bundle:
    """The file as a bundle, whichever of the three shapes it is in."""
    return bundle_of(load_document(path))
