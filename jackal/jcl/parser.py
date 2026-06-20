"""Grammar-based JCL parser: text -> Job."""

from __future__ import annotations

from importlib.resources import files

from lark import Lark, Transformer

from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step

_GRAMMAR = (files("jackal.jcl") / "grammar.lark").read_text()
_PARSER = Lark(_GRAMMAR, start="start", parser="earley")

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    status = DispStatus(words[0])
    normal = DispNormal(words[1]) if len(words) > 1 else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 else normal
    return Disp(status, normal, abnormal)


class _Build(Transformer):
    def NAME(self, t):
        return str(t)

    def DSNAME(self, t):
        return str(t)

    def DISPWORD(self, t):
        return str(t)

    def dsn_param(self, c):
        return ("dsn", c[0])

    def disp_param(self, c):
        return ("disp", _disp_from_words(tuple(c)))

    def dd_params(self, c):
        return dict(item for item in c if isinstance(item, tuple))

    def dd_card(self, c):
        name, params = c[0], c[1]
        return (
            "dd",
            DD(ddname=name, dsn=params["dsn"], disp=params.get("disp", _DEFAULT_DISP)),
        )

    def exec_card(self, c):
        return ("exec", c[0], c[1])

    def job_card(self, c):
        return ("job", c[0])

    def comment(self, c):
        return ("comment",)


def parse_jcl(text: str) -> Job:
    tree = _PARSER.parse(text if text.endswith("\n") else text + "\n")
    rows = _Build().transform(tree).children
    return _assemble(tuple(r for r in rows if r[0] != "comment"))


def _assemble(rows: tuple) -> Job:
    job_name = next(r[1] for r in rows if r[0] == "job")
    steps = _fold_steps(tuple(r for r in rows if r[0] in ("exec", "dd")))
    return Job(name=job_name, steps=steps)


def _fold_steps(rows: tuple) -> tuple[Step, ...]:
    starts = [i for i, r in enumerate(rows) if r[0] == "exec"]
    bounds = list(zip(starts, starts[1:] + [len(rows)]))
    return tuple(
        Step(
            name=rows[s][1],
            pgm=rows[s][2],
            dds=tuple(r[1] for r in rows[s + 1 : e] if r[0] == "dd"),
        )
        for s, e in bounds
    )
