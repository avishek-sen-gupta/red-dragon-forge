"""Bridge to the jcl-bridge JAR: JSON AST -> Job, and the JSON->model deserializer."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import TypeVar

from jackal.dsn import (
    DSN,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
    BackwardRef,
)
from jackal.model import (
    Cond,
    CondOp,
    DD,
    Disp,
    DispNormal,
    DispStatus,
    Job,
    ProcDef,
    Step,
)
from jackal.value_parts import Literal, Symbol, Value, resolve

_PREEXISTING_STATUSES = frozenset({DispStatus.OLD, DispStatus.SHR, DispStatus.MOD})

T = TypeVar("T")


def _value_from_json(parts: list[dict]) -> Value:
    result: list[Literal | Symbol] = []
    for part in parts:
        if part["type"] == "Symbol":
            result.append(Symbol(part["name"]))
        else:
            result.append(Literal(part["name"]))
    return tuple(result)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    """``DISP=(status,normal,abnormal)``, with any subparameter omissible.

    An omitted positional subparameter arrives as ``""`` (JclSerializer keeps the
    slot); a DD with no ``DISP=`` at all arrives as ``()``. The z/OS defaults are
    positional and chained rather than one fixed triple: the status defaults to
    NEW, the normal disposition to DELETE for a data set this step creates and
    KEEP for one that already existed, and the abnormal disposition to whichever
    normal disposition resolved. So a DD with no ``DISP=`` is (NEW,DELETE,DELETE)
    by the same rule, not by a separate constant.

    MOD is read as already-existing. It can be either — MOD creates the data set
    when it is absent and appends when it is present — and JCL alone cannot say
    which. Only ``status`` reaches the graph (``jcl_graph._DISP_TO_EDGE_KIND``),
    so this choice affects the model's fidelity and no edge.
    """

    def slot(i: int) -> str:
        return words[i] if i < len(words) else ""

    status = DispStatus(slot(0)) if slot(0) else DispStatus.NEW
    default_normal = (
        DispNormal.KEEP if status in _PREEXISTING_STATUSES else DispNormal.DELETE
    )
    normal = DispNormal(slot(1)) if slot(1) else default_normal
    abnormal = DispNormal(slot(2)) if slot(2) else normal
    return Disp(status, normal, abnormal)


def _dd_from_json(d: dict) -> DD:
    disp = _disp_from_words(tuple(d.get("disp_words", ())))
    dsn_value = _value_from_json(d.get("dsn", []))
    raw_dsn = (
        resolve(dsn_value) if not any(isinstance(p, Symbol) for p in dsn_value) else ""
    )
    if "backref" in d:
        br = d["backref"]
        dsn: DSN = BackwardRef(step=br["step"], ddname=br["ddname"])
    elif raw_dsn.startswith("*."):
        raise ValueError(
            f"Three-segment backward reference '{raw_dsn}' is not yet supported "
            "(see jackal-lz8 — requires PROC support from jackal-1o2.2)"
        )
    elif raw_dsn.startswith("&&"):
        dsn = TempRef(raw_dsn)
    elif raw_dsn == "" and d.get("dummy", False):
        dsn = DummyDSN()
    elif raw_dsn == "" and d.get("in_stream"):
        dsn = InStreamDSN()
    elif raw_dsn == "" and not dsn_value:
        dsn = NoDSN()
    else:
        dsn = DirectDSN(dsn_value)
    return DD(
        ddname=d["ddname"],
        dsn=dsn,
        disp=disp,
        in_stream=tuple(d.get("in_stream", ())),
        sysout=d.get("sysout", False),
    )


def _cond_from_json(c: dict) -> Cond:
    return Cond(code=c["code"], op=CondOp(c["op"]), step=c.get("step", ""))


def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"],
        pgm=s["pgm"],
        dds=tuple(_dd_from_json(d) for d in s["dds"]),
        conds=tuple(_cond_from_json(c) for c in s.get("cond", ())),
        parm=_value_from_json(s.get("parm", [])),
        proc_parms={k: _value_from_json(v) for k, v in s.get("proc_parms", {}).items()},
    )


def _job_from_json(data: dict) -> Job:
    return Job(
        name=data["name"],
        steps=tuple(_step_from_json(s) for s in data["steps"]),
        cond=tuple(_cond_from_json(c) for c in data.get("cond", ())),
    )


def _proc_from_json(data: dict) -> ProcDef:
    return ProcDef(
        name=data["name"],
        defaults={k: _value_from_json(v) for k, v in data.get("defaults", {}).items()},
        steps=tuple(_step_from_json(s) for s in data["steps"]),
    )


class JclParseError(Exception):
    """Raised when the jcl-bridge fails to parse JCL."""


def _malformed(out: str, cause: Exception) -> JclParseError:
    snippet = out[:120].replace("\n", " ")
    return JclParseError(
        f"bridge returned malformed/incomplete JSON: {cause} — output: {snippet!r}"
    )


def _from_bridge_json(out: str, build: Callable[[dict], T]) -> T:
    """Deserialize bridge output, reporting anything unusable as a parse failure.

    Wraps model construction as well as the JSON decode: ``_dd_from_json`` and the
    ``Disp*`` enums raise ``ValueError`` on shapes the model does not cover, and a
    caller cannot tell those apart from a bad member.

    Shared with JclStore, which deserializes the same output later from cache and
    so must fail with the same text as parsing it directly would have.
    """
    try:
        return build(json.loads(out))
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise _malformed(out, e) from e


def _validate_bridge_json(out: str) -> None:
    """Decode and discard, so a response that is not JSON fails here."""
    try:
        json.loads(out)
    except json.JSONDecodeError as e:
        raise _malformed(out, e) from e


def job_from_bridge_json(out: str) -> Job:
    """A Job from bridge output, as ``JclBridgeParser.parse`` would have built it."""
    return _from_bridge_json(out, _job_from_json)


class JclSubprocessRunner:
    """Production runner: invoke the bridge JAR, fail loud on non-zero exit."""

    def run(self, command: list[str], input_data: str) -> str:
        result = subprocess.run(
            command, input=input_data, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise JclParseError(
                f"jcl-bridge failed (exit {result.returncode}): {result.stderr}"
            )
        return result.stdout


class JclBridgeParser:
    """Parse JCL by delegating to the jcl-bridge JAR via subprocess."""

    def __init__(self, runner: JclSubprocessRunner, bridge_jar: str):
        self._runner = runner
        self._bridge_jar = bridge_jar

    def _run(self, text: str) -> str:
        return self._runner.run(["java", "-jar", self._bridge_jar], text)

    def parse(self, text: str) -> Job:
        return _from_bridge_json(self._run(text), _job_from_json)

    def parse_proc(self, text: str) -> ProcDef:
        return _from_bridge_json(self._run(text), _proc_from_json)

    def parse_to_json(self, text: str) -> str:
        """The bridge's JSON for this member, without building the Job.

        What JclStore caches: the JSON the bridge emitted, not what it
        deserialized to. Holding a Job per member does not scale to a corpus, and
        the bridge hands its output back as a string already, so caching costs a
        file write rather than a serializer.

        Decoded and thrown away here on purpose. A truncated or empty response
        has to fail while the member that produced it is still in hand — from
        cache it would surface much later, against a member name the store would
        have to carry solely to report it.
        """
        out = self._run(text)
        _validate_bridge_json(out)
        return out
