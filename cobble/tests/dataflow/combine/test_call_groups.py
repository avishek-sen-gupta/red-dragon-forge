"""Programs grouped by every call the fixpoint's tables say could link them."""

import json
from pathlib import Path

from cobble.dataflow.combine.call_groups import call_groups
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_row


def _member(
    fixpoint: Path,
    name: str,
    jumps: tuple[Jump, ...] = (),
    candidates: tuple[tuple[str, tuple[str, ...]], ...] = (),
    program: str = "",
) -> None:
    member = fixpoint / "members" / name
    member.mkdir(parents=True)
    (member / "jumps.jsonl").write_text(
        "".join(jump_row(jump) + "\n" for jump in jumps), encoding="utf-8"
    )
    (member / "targets.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "caller": program or name,
                    "node": f"{name}/{n}",
                    "kind": kind,
                    "candidates": list(names),
                    "reasons": ["incomplete-walk"],
                }
            )
            + "\n"
            for n, (kind, names) in enumerate(candidates)
        ),
        encoding="utf-8",
    )


def test_programs_group_by_literal_targets_candidates_and_transactions(
    tmp_path: Path,
) -> None:
    """A member is grouped under its directory's name even when its PROGRAM-ID,
    which its rows carry, differs."""
    _member(
        tmp_path,
        "A",
        (Jump("A", "A/0", 1, JumpKind.CALL, True, target=Fact(values=("B",))),),
    )
    _member(tmp_path, "B")
    _member(
        tmp_path,
        "C",
        (Jump("PROGC", "C/0", 1, JumpKind.XCTL, False),),
        (("program", ("D",)),),
        program="PROGC",
    )
    _member(tmp_path, "D")
    _member(
        tmp_path,
        "E",
        (Jump("E", "E/0", 1, JumpKind.XCTL, False, target=Fact(values=("ABSENT",))),),
        (("file", ("B",)),),
    )
    _member(
        tmp_path,
        "F",
        (
            Jump(
                "F",
                "F/0",
                1,
                JumpKind.RETURN_TRANSID,
                False,
                transid=Fact(values=("TXG ",)),
            ),
        ),
    )
    _member(tmp_path, "G")

    groups = call_groups(tmp_path, frozenset("ABCDEFG"), {"TXG": "G"})

    assert groups == (
        frozenset({"A", "B"}),
        frozenset({"C", "D"}),
        frozenset({"F", "G"}),
        frozenset({"E"}),
    )
