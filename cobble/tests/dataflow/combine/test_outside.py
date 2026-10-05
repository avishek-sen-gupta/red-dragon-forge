from pathlib import Path

from cobble.dataflow.combine.outside import outside_jumps
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_row


def test_outside_programs_are_named_counted_or_listed(tmp_path: Path) -> None:
    fixpoint, asg = tmp_path / "fx", tmp_path / "asg"
    for name, jump in (
        (
            "OUT1",
            Jump("OUT1", "X", 1, JumpKind.XCTL, False, target=Fact(values=("B",))),
        ),
        (
            "OUT2",
            Jump(
                "OUT2",
                "X",
                1,
                JumpKind.XCTL,
                False,
                target=Fact("WS-N@working_storage[0:8]"),
            ),
        ),
    ):
        (fixpoint / "members" / name).mkdir(parents=True)
        (fixpoint / "members" / name / "jumps.jsonl").write_text(
            jump_row(jump) + "\n", encoding="utf-8"
        )
    asg.mkdir()
    for name in ("B", "OUT1", "OUT2", "NORES"):
        (asg / f"{name}.json").write_text("{}", encoding="utf-8")

    assert outside_jumps(fixpoint, asg, frozenset({"B"}), {}) == OutsideJumps(
        known_into={"B": ("OUT1",)}, unresolved=1, without_results=("NORES",)
    )
