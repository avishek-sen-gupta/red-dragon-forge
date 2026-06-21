"""IDCAMS control-language parser: text -> tuple[Command, ...]."""

from __future__ import annotations

from importlib.resources import files

from lark import Lark, Token, Transformer, Tree

from jackal.idcams.commands import Command, DefineCluster, Delete, IfMaxcc, Repro

_GRAMMAR = (files("jackal.idcams") / "grammar.lark").read_text()
_PARSER = Lark(_GRAMMAR, start="start", parser="earley")


class _Build(Transformer):
    def NAME(self, t: Token) -> str:
        return str(t)

    def DSNAME(self, t: Token) -> str:
        return str(t)

    def INT(self, t: Token) -> int:
        return int(t)

    def OP(self, t: Token) -> str:
        return str(t)

    def delete_cmd(self, c: list) -> Delete:
        return Delete(dsn=c[0])

    def name_param(self, c: list) -> tuple:
        return ("name", c[0])

    def keys_param(self, c: list) -> tuple:
        return ("keys", int(c[0]), int(c[1]))

    def recordsize_param(self, c: list) -> tuple:
        return ("recordsize", int(c[0]))

    def define_cmd(self, c: list) -> DefineCluster:
        name = next(v for k, *v in c if k == "name")[0]
        key_length, key_offset = next((v[0], v[1]) for k, *v in c if k == "keys")
        record_size = next(v[0] for k, *v in c if k == "recordsize")
        return DefineCluster(
            name=name,
            key_length=key_length,
            key_offset=key_offset,
            record_size=record_size,
        )

    def repro_cmd(self, c: list) -> Repro:
        return Repro(infile_dd=c[0], outfile_dd=c[1])

    def if_cmd(self, c: list) -> IfMaxcc:
        op, value, set_value = c[0], int(c[1]), int(c[2])
        return IfMaxcc(op=op, value=value, set_value=set_value)

    def command(self, c: list) -> Command:
        return c[0]


def parse_idcams(text: str) -> tuple[Command, ...]:
    """Parse IDCAMS control statements and return a tuple of Command objects."""
    src = text if text.endswith("\n") else text + "\n"
    tree = _PARSER.parse(src)
    result = _Build().transform(tree)
    return tuple(result.children)
