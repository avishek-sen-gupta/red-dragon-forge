"""Grammar-based JCL parser: text -> Job."""

from __future__ import annotations

import re

from importlib.resources import files

from lark import Lark, Token, Transformer

from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step

_GRAMMAR = (files("jackal.jcl") / "grammar.lark").read_text()
_PARSER = Lark(_GRAMMAR, start="start", parser="earley")

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)

# JOB statement may span multiple continuation lines (// prefix on next line).
# The grammar only needs the job name from the JOB card, so we normalise
# the JOB statement to a single line with just the account string before parsing.
# A JCL continuation line starts with "//" followed immediately by a space/tab
# (not a name char or "*"), distinguishing it from EXEC/DD/comment cards.
_JOB_CONTINUATION = re.compile(
    r"(//[A-Z#@$][A-Z0-9#@$]*\s+JOB\s+)([^\n]+(?:\n//[ \t][^\n]*)*)",
    re.MULTILINE,
)


def _strip_job_continuations(text: str) -> str:
    """Collapse JOB card continuation lines, strip parameters, and remove blank lines."""

    def _normalise_job(m: re.Match[str]) -> str:
        prefix = m.group(1)
        body = m.group(2)
        # The first token is the account string (quoted or unquoted); keep only that.
        account = body.split(",")[0].strip()
        return prefix + account + "\n"

    normalised = _JOB_CONTINUATION.sub(_normalise_job, text)
    # Remove blank lines that the grammar cannot handle
    return "\n".join(line for line in normalised.splitlines() if line.strip()) + "\n"


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

    def unknown_param(self, c: list) -> tuple:
        return ("unknown",)

    def dd_params(self, c):
        return dict(
            item for item in c if isinstance(item, tuple) and item[0] != "unknown"
        )

    def dd_card(self, c):
        name, params = c[0], c[1]
        return (
            "dd",
            DD(ddname=name, dsn=params["dsn"], disp=params.get("disp", _DEFAULT_DISP)),
        )

    def dd_instream(self, c):
        name = c[0]
        lines = tuple(
            str(tok)
            for tok in c
            if isinstance(tok, Token) and tok.type == "INSTREAM_LINE"
        )
        return ("dd", DD(ddname=name, dsn="", disp=_DEFAULT_DISP, in_stream=lines))

    def dd_sysout(self, c):
        name = c[0]
        return ("dd", DD(ddname=name, dsn="", disp=_DEFAULT_DISP, sysout=True))

    def exec_card(self, c):
        return ("exec", c[0], c[1])

    def job_card(self, c):
        return ("job", c[0])

    def comment(self, c):
        return ("comment",)


def parse_jcl(text: str) -> Job:
    text = _strip_job_continuations(text)
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
