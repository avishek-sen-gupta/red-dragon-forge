"""cobble-srccfg-subgraph: a hand-picked slice of a CFG, rendered as a DOT/
PNG/SVG picture, for a question a full-program render is too dense to answer.

Usage:
    uv run cobble-srccfg-subgraph \\
        --cfg /tmp/cfg-MYPROG.jsonl --program MYPROG \\
        --prefix VALIDATE-OPTION/4 --prefix VALIDATE-OPTION/5 \\
        --prefix CHECK-ACCESS \\
        --drop-suffix '#dispatch' \\
        --drop-target MAP-FAIL#label --drop-target LENGTH-ERROR#label \\
        --out /tmp/dispatch

    # cross-program: --program accepts more than one, merging their nodes/edges
    uv run cobble-srccfg-subgraph \\
        --cfg /tmp/cfg-CALLERPGM.jsonl --program CALLERPGM --program CALLEEPGM \\
        --prefix CALL-CALLEEPGM --prefix START-ROUTINE/6 \\
        --prefix READ-RECORD/1 --prefix ABORT-PROCESS \\
        --out /tmp/abort-trace

Writes <out>.dot, <out>.png, <out>.svg. Requires graphviz (``dot``) and, for
wide fan-outs (``--balance``), ``unflatten`` (both ship with graphviz).

IMPORTANT: keep ``#raise`` nodes unless checked they're not load-bearing.
``#raise`` is the "did this EXEC CICS verb raise a handled condition?"
decision point; only ``#dispatch`` (its error fan-out) is pure noise.
Dropping ``#raise`` silently cuts the FALSE (no-error) edge into whatever
follows -- connectivity enforcement will try to bridge the gap rather than
silently rendering two floating halves, but an explicit ``--drop-suffix``
is still a declared intent the bridge logic can't second-guess.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.bundle import CfgDocumentError, load_bundle
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.subgraph import SubgraphError, build_dot

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-srccfg-subgraph",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cfg", required=True, type=Path, help="a CFG file cobble-srccfg-build wrote"
    )
    parser.add_argument(
        "--program",
        action="append",
        required=True,
        dest="programs",
        help="program name within the CFG file; repeatable for a cross-program render",
    )
    parser.add_argument(
        "--prefix",
        action="append",
        required=True,
        dest="prefixes",
        help="separator-aware node-id prefix to include; repeatable",
    )
    parser.add_argument(
        "--drop-suffix",
        action="append",
        default=[],
        dest="drop_suffixes",
        help="node-id suffix to exclude even if prefix-matched (e.g. #dispatch); repeatable",
    )
    parser.add_argument(
        "--drop-target",
        action="append",
        default=[],
        dest="drop_targets",
        help="edge target id to exclude (e.g. an error-handler label); repeatable",
    )
    parser.add_argument(
        "--short",
        action="append",
        default=[],
        dest="shorts",
        metavar="LONG=SHORT",
        help="label-shortening replacement, e.g. VALIDATE-OPTION=VO; repeatable",
    )
    parser.add_argument(
        "--balance",
        action="store_true",
        help="pipe through `unflatten -f -l 2 -c 5` before rendering (use for wide "
        "flat fan-outs, e.g. GO TO DEPENDING ON with 10+ branches)",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output path stem; writes <out>.dot/.png/.svg",
    )
    return parser


def _selected(cfgs: Sequence[Cfg], wanted: Sequence[str]) -> tuple[Cfg, ...]:
    by_name = {cfg.program: cfg for cfg in cfgs}
    missing = [p for p in wanted if p not in by_name]
    if missing:
        raise SubgraphError(
            f"not in this CFG file: {missing} (have: {sorted(by_name)})"
        )
    return tuple(by_name[p] for p in wanted)


def _dot_built(arguments: argparse.Namespace) -> tuple[str, list[str], bool]:
    bundle = load_bundle(arguments.cfg)
    cfgs = _selected(bundle.cfgs, arguments.programs)
    short_prefixes = dict(s.split("=", 1) for s in arguments.shorts)
    return build_dot(
        cfgs,
        tuple(arguments.prefixes),
        tuple(arguments.drop_suffixes),
        frozenset(arguments.drop_targets),
        short_prefixes,
    )


def _bridge_kind(used_weak: bool) -> str:
    if used_weak:
        return "textual FALLTHRU only -- not a provable jump, verify it's meaningful"
    return "real control-flow edges"


def _bridge_note(bridged: Sequence[str], used_weak: bool) -> str:
    if not bridged:
        return ""
    return (
        f"bridged in {len(bridged)} node(s) to keep the graph connected via "
        f"{_bridge_kind(used_weak)} (shown gray): {list(bridged)}"
    )


def _balanced(dot_path: Path, out: Path) -> Path:
    balanced = out.with_name(out.name + "-balanced.dot")
    result = subprocess.run(
        ["unflatten", "-f", "-l", "2", "-c", "5", str(dot_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    balanced.write_text(result.stdout)
    return balanced


def _render_input(dot_path: Path, out: Path, balance: bool) -> Path:
    if not balance:
        return dot_path
    return _balanced(dot_path, out)


def _rendered(render_input: Path, out: Path, fmt: str) -> Path:
    out_file = out.with_suffix(f".{fmt}")
    subprocess.run(
        ["dot", f"-T{fmt}", str(render_input), "-o", str(out_file)], check=True
    )
    return out_file


def _written(arguments: argparse.Namespace, document: str) -> tuple[Path, ...]:
    dot_path = arguments.out.with_suffix(".dot")
    dot_path.write_text(document)
    render_input = _render_input(dot_path, arguments.out, arguments.balance)
    return tuple(_rendered(render_input, arguments.out, fmt) for fmt in ("png", "svg"))


def _logged_bridge(bridged: Sequence[str], used_weak: bool) -> None:
    note = _bridge_note(bridged, used_weak)
    if note:
        logger.info(note)


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    try:
        document, bridged, used_weak = _dot_built(arguments)
    except (CfgDocumentError, SubgraphError, FileNotFoundError) as error:
        logger.error("%s", error)
        return 1
    _logged_bridge(bridged, used_weak)
    for out_file in _written(arguments, document):
        logger.info("wrote %s", out_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
