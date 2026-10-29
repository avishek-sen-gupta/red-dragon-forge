"""Facts on disk: one tab-separated file per relation, de-duplicated and sorted, and the schema declaring them."""

from collections.abc import Sequence
from pathlib import Path

from cobble.experimental.datalog.facts import Facts, Row, Value
from cobble.experimental.datalog.relation import Relation

SCHEMA_FILE = "schema.dl"
_SPACED = str.maketrans({"\t": " ", "\n": " ", "\r": " "})


def _cleaned(value: Value) -> str:
    return str(value).translate(_SPACED)


def _lines(rows: Sequence[Row]) -> str:
    texts = sorted({tuple(map(_cleaned, row)) for row in rows})
    return "".join("\t".join(text) + "\n" for text in texts)


def write_facts(out: Path, facts: Sequence[Facts]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tuple(
        (out / f"{one.relation.name}.facts").write_text(
            _lines(one.rows), encoding="utf-8"
        )
        for one in facts
    )
    (out / SCHEMA_FILE).write_text(
        schema_text(tuple(one.relation for one in facts)), encoding="utf-8"
    )


def schema_text(relations: Sequence[Relation]) -> str:
    declared = "".join(relation.schema() for relation in relations)
    return f"#ifndef SCHEMA_DL\n#define SCHEMA_DL\n{declared}#endif\n"
