"""checker.py — the numbers that decide whether a name is a conduit.

The loop this serves: build the graph, look for unusually high fan-in/fan-out,
judge whether each hub is a pass-through variable, add the ones that are, repeat.
The judgment is a reading of these five numbers plus where the name is declared;
what makes it mechanical rather than a guess is `adjacent`.

Measured over 40 programs, adjacency separates the two populations cleanly with
nothing in between:

    WS-EDIT-PAY     1.00    conduit -- written then read, every time
    WS-NUMERIAL     0.95    conduit
    WS-NUM-TRIM     0.90    conduit
    RECG-NUM-ID     0.10    VSAM key -- written here, read in a later paragraph
    ERRMSGO         0.00    screen field -- an answer, not a conduit
    DFHCOMMAREA     0.00    commarea

So no naming convention is needed, and none is used: WS-NUMERIAL and WS-NUM-AMT
look alike and score 0.95 against 0.44.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from cobble.dataflow.depgraph.graph import Edge, Passthrough

# The cut a hub has to clear to be judged a conduit, and the traffic it has to
# carry before the fraction means anything. 4 writes at 1.00 is one paragraph
# repeated, not an idiom.
ADJACENCY_CUT = 0.9
MIN_WRITES = 5


def conduit_stats(edges: Sequence[Edge], window: int = 1) -> dict[str, dict]:
    """Per name, the numbers that decide whether it is a conduit.

    fan_in/fan_out    distinct names flowing in / out
    writes            how many edges write it -- 1 means single-purpose,
                      9 means reused for nine unrelated pairs (WS-NUMERIAL)
    reads             how many edges read it
    adjacent          of the edges INTO it, the fraction immediately followed by
                      an edge OUT of it. A real conduit is written and then read
                      at once, every time, so this is near 1.0. Low means the
                      value is written here and consumed far away, and collapsing
                      it would guess.
    """
    into: dict[str, list[tuple[str, int]]] = defaultdict(list)
    out_of: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for a, b, i, _verb in edges:
        into[b].append((a, i))
        out_of[a].append((b, i))

    stats: dict[str, dict] = {}
    for name in set(into) | set(out_of):
        ins, outs = into.get(name, ()), out_of.get(name, ())
        out_idx = sorted(j for _, j in outs)
        paired = sum(1 for _, i in ins if any(0 < j - i <= window for j in out_idx))
        stats[name] = {
            "fan_in": len({a for a, _ in ins}),
            "fan_out": len({b for b, _ in outs}),
            "writes": len(ins),
            "reads": len(outs),
            "adjacent": paired / len(ins) if ins else 0.0,
        }
    return stats


def merge_stats(per_program: Iterable[Mapping[str, dict]]) -> dict[str, dict]:
    """Sum per-program stats into one corpus view, keeping adjacency weighted.

    Weighted by writes, not averaged over programs: a name that is a conduit in
    the one program that writes it 40 times and incidental in ten that write it
    once should read as a conduit.
    """
    agg: dict[str, dict] = defaultdict(
        lambda: {
            "fan_in": 0,
            "fan_out": 0,
            "writes": 0,
            "reads": 0,
            "paired": 0.0,
            "programs": 0,
        }
    )
    for stats in per_program:
        for name, s in stats.items():
            a = agg[name]
            a["fan_in"] += s["fan_in"]
            a["fan_out"] += s["fan_out"]
            a["writes"] += s["writes"]
            a["reads"] += s["reads"]
            a["paired"] += s["adjacent"] * s["writes"]
            a["programs"] += 1
    for a in agg.values():
        a["adjacent"] = a["paired"] / a["writes"] if a["writes"] else 0.0
    return dict(agg)


def hub_lines(title: str, agg: Mapping[str, dict], limit: int = 25) -> list[str]:
    """The hub table, ranked by fan_in * fan_out. Both factors, because a name
    with 40 writers and one reader is a screen field, not a hub."""
    lines = [
        f"=== {title}",
        f"    {'name':<32} {'in':>5} {'out':>5} {'wr':>5} {'rd':>5} {'adj':>5} progs",
    ]
    ranked = sorted(agg.items(), key=lambda kv: -(kv[1]["fan_in"] * kv[1]["fan_out"]))
    for name, s in ranked[:limit]:
        if s["fan_in"] * s["fan_out"] == 0:
            break
        lines.append(
            f"    {name:<32} {s['fan_in']:>5} {s['fan_out']:>5} "
            f"{s['writes']:>5} {s['reads']:>5} {s['adjacent']:>5.2f} {s['programs']}"
        )
    return lines


def candidate_lines(
    agg: Mapping[str, dict], passthrough: Passthrough, limit: int = 30
) -> list[str]:
    """The names to add to the pass-through set before the next round.

    Read this list, check where each name is declared (nodes.json carries the
    section and record), and add the ones that are conduits to the config's
    [collapse] passthrough_names. An empty list is the loop having converged.
    """
    lines = [
        f"=== CONDUIT CANDIDATES  (adjacency >= {ADJACENCY_CUT}, "
        f"writes >= {MIN_WRITES}, not already pass-through)",
        "    add the conduits among these to [collapse] passthrough_names, rerun",
        f"    {'name':<32} {'in':>5} {'out':>5} {'wr':>5} {'adj':>5} progs",
    ]
    cands = [
        (n, s)
        for n, s in agg.items()
        if s["adjacent"] >= ADJACENCY_CUT
        and s["writes"] >= MIN_WRITES
        and n not in passthrough
    ]
    for name, s in sorted(cands, key=lambda kv: -kv[1]["writes"])[:limit]:
        lines.append(
            f"    {name:<32} {s['fan_in']:>5} {s['fan_out']:>5} "
            f"{s['writes']:>5} {s['adjacent']:>5.2f} {s['programs']}"
        )
    return lines
