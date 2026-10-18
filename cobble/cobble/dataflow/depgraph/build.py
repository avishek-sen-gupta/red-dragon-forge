"""build.py — walk the cached ASGs, run both passes, emit the graph.

    uv run cobble-depgraph --config config/depgraph.local.toml   # --limit 40 for a
                                                                # fast round

Reads the ASG cache cobble-parse-corpus wrote, so it needs no JVM and no corpus
source. One round of the judgment loop is this command, then a read of the CONDUIT
CANDIDATES table it prints, then an edit to [collapse] passthrough_names in the
config.

Three files land in graph_dir:

    edges.jsonl  {"src","dst","program","seq","verb"} -- one row per surviving
                 edge, streamed, because 3779 programs at ~150 edges each is
                 ~570k rows. "seq" is the ordinal of the data-carrying statement
                 the edge came from (see graph.py); "verb" is what made it.
    nodes.jsonl  one object per name: where it is declared, whether it is
                 pass-through, which programs it appears in, and its five numbers.
                 JSONL, not one JSON array: the array had to be built whole in
                 memory and then re-read whole, and a per-line file is greppable
                 for one name without a parser.
    pairs.json   {"src","dst","count","verbs"} -- edges.jsonl deduplicated, which
                 is the dependency graph proper. "verbs" is the per-verb count for
                 the pair, so a pair moved by both a MOVE and a COMPUTE says so.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.checker import (
    candidate_lines,
    conduit_stats,
    hub_lines,
    merge_stats,
)
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.depgraph.config import load_depgraph_config
from cobble.dataflow.depgraph.flows import (
    FILE_PREFIX,
    MAP_PREFIX,
    PROGRAM_PREFIX,
    QUEUE_PREFIX,
    TRANSID_PREFIX,
)
from cobble.dataflow.depgraph.graph import Passthrough, declarations, pass1, pass2
from cobble.path_utils import ensure_dir
from cobble.parsing.asg_cache import programs_at

logger = logging.getLogger(__name__)

# An identity node is not declared anywhere, so its "section" is what it IS. Kept
# distinct from FILE, which means the COBOL FILE SECTION: DATASET:LAYOUT1 is the
# dataset, LAYOUT1-REC in FILE SECTION is the record area it lands in.
IDENTITY_SECTIONS = {
    FILE_PREFIX: "DATASET",
    MAP_PREFIX: "MAP",
    PROGRAM_PREFIX: "PROGRAM",
    QUEUE_PREFIX: "TSQUEUE",
    TRANSID_PREFIX: "TRANSID",
}


def _section_of(name: str, declared: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """(declaring section, root record) for a name, identity nodes included."""
    for prefix, section in IDENTITY_SECTIONS.items():
        if name.startswith(prefix):
            return section, ""
    return declared.get(name, ("<undeclared>", ""))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a depgraph TOML config (see cobble/dataflow/depgraph/config.py)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after this many programs, for a fast round (default: all)",
    )
    return parser.parse_args()


def main() -> int:
    configure_cli_logging()
    args = _parse_args()
    config = load_depgraph_config(args.config)
    ensure_dir(config.graph_dir)
    window = config.collapse_window
    passthrough = Passthrough(config.passthrough_names, config.passthrough_patterns)
    logger.info(
        "pass-through: %d names, %d patterns, window=%d",
        len(config.passthrough_names),
        len(config.passthrough_patterns),
        window,
    )

    paths = sorted(config.asg_dir.glob("*.json"))
    if args.limit:
        paths = paths[: args.limit]
    logger.info(
        "%d cached ASGs in %s, emitting to %s/",
        len(paths),
        config.asg_dir,
        config.graph_dir,
    )
    if not paths:
        logger.info("!! nothing to walk -- run cobble-parse-corpus first")
        return 1

    before: list[dict] = []
    after: list[dict] = []
    grand: Counter = Counter()
    # Keyed (src, dst, verb) rather than a Counter per pair: one flat dict of
    # counts is a fraction of the memory of 300k small ones, and pairs.json's rows
    # are one group-by away.
    pair_verbs: Counter = Counter()
    node_programs: dict[str, set[str]] = defaultdict(set)
    node_decl: dict[str, tuple[str, str]] = {}
    t0 = time.perf_counter()

    with (config.graph_dir / "edges.jsonl").open("w") as edge_fh:
        for n, path in enumerate(paths, 1):
            program = path.stem
            with cached_asg_dialect_parsers_registered():
                programs = programs_at(path)

            for asg in programs:
                for name, where in declarations(asg).items():
                    node_decl.setdefault(name, where)

                e1, t1 = pass1(asg)
                e2, t2 = pass2(e1, passthrough, window)
                grand["programs"] += 1
                grand["pass1_edges"] += len(e1)
                grand["pass2_edges"] += len(e2)
                # Every key, including stmt_/empty_/skip_: together they are the verb
                # table's coverage report, and picking four by hand is how the last
                # round failed to notice that all 49893 EXEC CICS statements were
                # arriving empty.
                for k, v in t1.items():
                    grand[k] += v
                for k, v in t2.items():
                    grand[f"collapse_{k}"] += v

                before.append(conduit_stats(e1, window))
                after.append(conduit_stats(e2, window))
                for a, b, i, verb in e2:
                    pair_verbs[(a, b, verb)] += 1
                    node_programs[a].add(program)
                    node_programs[b].add(program)
                    edge_fh.write(
                        json.dumps(
                            {
                                "src": a,
                                "dst": b,
                                "program": program,
                                "seq": i,
                                "verb": verb,
                            }
                        )
                        + "\n"
                    )

            # Every 10 for the first 100, then every 100. Loading an ASG and
            # building its layout is about a second, so waiting for 100 of them
            # before the first line is two minutes that look like a hang.
            if (n <= 100 and n % 10 == 0) or n % 100 == 0 or n == len(paths):
                elapsed = time.perf_counter() - t0
                logger.info(
                    "[%5d/%d] %-10s programs=%-3d edges=%-8d "
                    "elapsed=%.1fm eta=%.1fm",
                    n,
                    len(paths),
                    program,
                    len(programs),
                    grand["pass2_edges"],
                    elapsed / 60,
                    (len(paths) - n) / (n / elapsed) / 60 if elapsed else 0,
                )

    agg_before = merge_stats(before)
    agg_after = merge_stats(after)

    with (config.graph_dir / "nodes.jsonl").open("w") as node_fh:
        for name, s in sorted(agg_after.items()):
            section, record = _section_of(name, node_decl)
            node_fh.write(
                json.dumps(
                    {
                        "name": name,
                        "section": section,
                        "record": record,
                        "passthrough": name in passthrough,
                        "programs": sorted(node_programs.get(name, ())),
                        "fan_in": s["fan_in"],
                        "fan_out": s["fan_out"],
                        "writes": s["writes"],
                        "reads": s["reads"],
                        "adjacent": round(s["adjacent"], 3),
                    }
                )
                + "\n"
            )

    pairs: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for (a, b, verb), count in pair_verbs.items():
        pairs[(a, b)][verb] += count
    (config.graph_dir / "pairs.json").write_text(
        json.dumps(
            [
                {
                    "src": a,
                    "dst": b,
                    "count": sum(verbs.values()),
                    "verbs": dict(sorted(verbs.items())),
                }
                for (a, b), verbs in sorted(pairs.items())
            ],
            indent=1,
        )
        + "\n"
    )

    logger.info("")
    logger.info("=== %d programs", grand["programs"])
    for k, v in sorted(grand.items()):
        logger.info("  %-28s %10d", k, v)
    logger.info("  %-28s %10d", "distinct pairs", len(pairs))
    logger.info("  %-28s %10d", "nodes", len(agg_after))
    logger.info("wrote nodes.jsonl, pairs.json, edges.jsonl -> %s/", config.graph_dir)
    logger.info("")
    for line in hub_lines("HUBS BEFORE COLLAPSE", agg_before):
        logger.info(line)
    logger.info("")
    for line in hub_lines("HUBS AFTER COLLAPSE", agg_after):
        logger.info(line)
    logger.info("")
    for line in candidate_lines(agg_before, passthrough):
        logger.info(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
