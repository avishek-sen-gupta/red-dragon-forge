"""Bridge to the jcl-bridge JAR: JSON AST -> Job, and the JSON->model deserializer."""

from __future__ import annotations

import json
import subprocess

from port.jackal.dsn import (
    DSN,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
    BackwardRef,
)
from port.jackal.model import (
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
from port.jackal.value_parts import Literal, Symbol, Value, resolve

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


def _value_from_json(parts: list[dict]) -> Value:
    result: list[Literal | Symbol] = []
    for part in parts:
        if part["type"] == "Symbol":
            result.append(Symbol(part["name"]))
        else:
            result.append(Literal(part["name"]))
    return tuple(result)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    status = DispStatus(words[0])
    normal = DispNormal(words[1]) if len(words) > 1 else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 else normal
    return Disp(status, normal, abnormal)


def _dd_from_json(d: dict) -> DD:
    words = tuple(d.get("disp_words", ()))
    disp = _disp_from_words(words) if words else _DEFAULT_DISP
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

    def parse(self, text: str) -> Job:
        command = ["java", "-jar", self._bridge_jar]
        out = self._runner.run(command, text)
        try:
            return _job_from_json(json.loads(out))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            snippet = out[:120].replace("\n", " ")
            raise JclParseError(
                f"bridge returned malformed/incomplete JSON: {e} — output: {snippet!r}"
            ) from e

    def parse_proc(self, text: str) -> ProcDef:
        command = ["java", "-jar", self._bridge_jar]
        out = self._runner.run(command, text)
        try:
            return _proc_from_json(json.loads(out))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            snippet = out[:120].replace("\n", " ")
            raise JclParseError(
                f"bridge returned malformed/incomplete JSON: {e} — output: {snippet!r}"
            ) from e
