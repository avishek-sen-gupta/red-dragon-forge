"""Bridge to the jcl-bridge JAR: its JSON, validated as jackal.jcl.wire models, as a Job."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from typing import TypeVar

from jackal.jcl import wire
from jackal.model import Job, ProcDef
from pydantic import ValidationError

T = TypeVar("T")


def _job(document: wire.JobDoc | wire.ProcDoc) -> Job:
    return document.job()


def _proc(document: wire.JobDoc | wire.ProcDoc) -> ProcDef:
    return document.proc()


class JclParseError(Exception):
    """Raised when the jcl-bridge fails to parse JCL."""


def _malformed(out: str, cause: Exception) -> JclParseError:
    snippet = out[:120].replace("\n", " ")
    return JclParseError(
        f"bridge returned malformed/incomplete JSON: {cause} — output: {snippet!r}"
    )


def _from_bridge_json(out: str, build: Callable[[wire.JobDoc | wire.ProcDoc], T]) -> T:
    """Deserialize bridge output, reporting anything unusable as a parse failure.

    Wraps model construction as well as validation: the mapping and the ``Disp*``
    enums raise ``ValueError`` on shapes today's model does not cover, and a
    caller cannot tell those apart from a bad member.

    Shared with JclStore, which deserializes the same output later from cache and
    so must fail with the same text as parsing it directly would have.
    """
    try:
        return build(wire.Document.model_validate_json(out).root)
    except ValueError as e:
        raise _malformed(out, e) from e


def _validate_bridge_json(out: str) -> None:
    """Validate and discard, so a response that breaks the contract fails here."""
    try:
        wire.Document.model_validate_json(out)
    except ValidationError as e:
        raise _malformed(out, e) from e


def job_from_bridge_json(out: str) -> Job:
    """A Job from bridge output, as ``JclBridgeParser.parse`` would have built it."""
    return _from_bridge_json(out, _job)


class JclSubprocessRunner:
    """Production runner: invoke the bridge JAR, fail loud on non-zero exit."""

    def run(self, command: Sequence[str], input_data: str) -> str:
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
        return _from_bridge_json(self._run(text), _job)

    def parse_proc(self, text: str) -> ProcDef:
        return _from_bridge_json(self._run(text), _proc)

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
