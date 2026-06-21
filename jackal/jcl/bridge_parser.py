"""Bridge to the jcl-bridge JAR: JSON AST -> Job, and the JSON->model deserializer."""

from __future__ import annotations

from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step

_DEFAULT_DISP = Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP)


def _disp_from_words(words: tuple[str, ...]) -> Disp:
    status = DispStatus(words[0])
    normal = DispNormal(words[1]) if len(words) > 1 else DispNormal.KEEP
    abnormal = DispNormal(words[2]) if len(words) > 2 else normal
    return Disp(status, normal, abnormal)


def _dd_from_json(d: dict) -> DD:
    words = tuple(d.get("disp_words", ()))
    disp = _disp_from_words(words) if words else _DEFAULT_DISP
    return DD(
        ddname=d["ddname"],
        dsn=d.get("dsn", ""),
        disp=disp,
        in_stream=tuple(d.get("in_stream", ())),
        sysout=d.get("sysout", False),
    )


def _step_from_json(s: dict) -> Step:
    return Step(
        name=s["name"], pgm=s["pgm"], dds=tuple(_dd_from_json(d) for d in s["dds"])
    )


def _job_from_json(data: dict) -> Job:
    return Job(
        name=data["name"], steps=tuple(_step_from_json(s) for s in data["steps"])
    )
