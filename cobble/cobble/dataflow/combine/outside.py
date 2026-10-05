"""What programs outside a linked set say about jumping into it — read, never analysed."""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_from_row

_PROGRAM_JUMPS = frozenset({JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL})
_TRANSACTION_JUMPS = frozenset({JumpKind.RETURN_TRANSID, JumpKind.START})


def _jumps(directory: Path) -> tuple[Jump, ...]:
    path = directory / "jumps.jsonl"
    if not path.is_file():
        return ()
    return tuple(
        jump_from_row(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _targets(jump: Jump, transactions: Mapping[str, str]) -> tuple[str, ...]:
    if jump.kind in _PROGRAM_JUMPS:
        return tuple(value.rstrip() for value in jump.target.values)
    if jump.kind in _TRANSACTION_JUMPS:
        return tuple(
            transactions[value.rstrip()]
            for value in jump.transid.values
            if value.rstrip() in transactions
        )
    return ()


def _unresolved(jump: Jump) -> bool:
    return (
        jump.kind in _PROGRAM_JUMPS
        and bool(jump.target.extent)
        and not jump.target.values
    )


def _analysed(fixpoint_dir: Path) -> frozenset[str]:
    members = fixpoint_dir / "members"
    if not members.is_dir():
        return frozenset()
    return frozenset(path.name for path in members.iterdir() if path.is_dir())


def _known_into(
    jumps: tuple[Jump, ...], inside: frozenset[str], transactions: Mapping[str, str]
) -> Mapping[str, tuple[str, ...]]:
    pairs = sorted(
        {
            (target, jump.program)
            for jump in jumps
            for target in _targets(jump, transactions)
            if target in inside
        }
    )
    return MappingProxyType(
        {
            target: tuple(program for t, program in pairs if t == target)
            for target in sorted({target for target, _ in pairs})
        }
    )


def outside_jumps(
    fixpoint_dir: Path,
    asg_dir: Path,
    inside: frozenset[str],
    transactions: Mapping[str, str],
) -> OutsideJumps:
    analysed = _analysed(fixpoint_dir)
    members = fixpoint_dir / "members"
    jumps = tuple(
        jump for name in sorted(analysed - inside) for jump in _jumps(members / name)
    )
    return OutsideJumps(
        known_into=_known_into(jumps, inside, transactions),
        unresolved=sum(1 for jump in jumps if _unresolved(jump)),
        without_results=tuple(
            sorted(
                path.stem
                for path in asg_dir.glob("*.json")
                if path.stem not in analysed and path.stem not in inside
            )
        ),
    )
