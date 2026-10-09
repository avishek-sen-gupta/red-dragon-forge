"""Finding every EXEC CICS statement in an ASG: in source order, each once, at any depth or size."""

from dataclasses import dataclass, field
from functools import reduce

from cics.statements import ExecCicsStatement
from cobble.cics.exec_cics_walk import exec_cics_statements


@dataclass(frozen=True)
class _Block:
    body: tuple["_Part", ...] = ()
    named: dict[str, "_Part"] = field(default_factory=dict)


_Part = _Block | ExecCicsStatement | list["_Part"] | str | int | bool | None


def _verb(name: str) -> ExecCicsStatement:
    return ExecCicsStatement(verb=name, options={})


def test_statements_come_back_in_source_order_each_once_however_deep_or_large() -> None:
    first, second, third, shared = (
        _verb("XCTL"),
        _verb("LINK"),
        _verb("RETURN"),
        _verb("READ"),
    )
    nested = _Block(
        body=(
            first,
            [_Block(body=(second, shared)), "text", 7, True, None],
            _Block(named={"later": third, "again": shared}),
        )
    )
    deep: _Part = reduce(
        lambda inner, _: _Block(body=(inner,)), range(20_000), _verb("SEND MAP")
    )
    wide = _Block(body=tuple(_Block(body=("x", 1, [2, 3])) for _ in range(100_000)))

    assert [s.verb for s in exec_cics_statements(nested)] == [
        "XCTL",
        "LINK",
        "READ",
        "RETURN",
    ]
    assert [s.verb for s in exec_cics_statements(deep)] == ["SEND MAP"]
    assert exec_cics_statements(wide) == ()
