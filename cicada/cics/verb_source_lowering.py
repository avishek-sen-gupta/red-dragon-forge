"""Production verb source for CICS flow analysis: lower each program through the
CICS lowering strategy and collect CicsVerb events off a CollectingObserver.

This is the driver behind cics.flow_map's public entry points. The knowledge-
graph pipeline does NOT use this module — it sources the same
{program: [CicsVerb]} shape from a typed-ASG walk instead — which is why the
lowering imports live here, isolated from the shared cics.flow_graph_core.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from cics.flow_observer import CicsVerb


class _CollectingObserver:
    """Accumulates CicsVerb events for one program compilation, tagging program name."""

    def __init__(self, program_name: str) -> None:
        self._program_name = program_name
        self.verbs: list[CicsVerb] = []

    def on_verb(self, verb: CicsVerb) -> None:
        # Strategy leaves verb.program = ""; tag it here with the known program name.
        self.verbs.append(
            CicsVerb(
                verb=verb.verb,
                program=self._program_name,
                map_name=verb.map_name,
                mapset_name=verb.mapset_name,
                xctl_target=verb.xctl_target,
                transid=verb.transid,
                file_name=verb.file_name,
            )
        )


def compile_all_programs(
    csd_source: str,
    cobol_sources: dict[str, bytes],
    parser: Any,
) -> tuple[dict[str, str], dict[str, list[CicsVerb]]]:
    """Parse the CSD and compile each distinct referenced program once, via the
    CICS lowering strategy. Returns (transid_to_program, {program: [CicsVerb]})."""
    from cics.csd_parse import parse_csd  # noqa: PLC0415
    from cics.bootstrap import compile_cics_program  # noqa: PLC0415
    from cics.coprocessor import build_cics_spec  # noqa: PLC0415

    # parse_csd expects a Path; write CSD text to a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    transid_to_program = parse_csd(csd_path)
    csd_path.unlink(missing_ok=True)

    compiled_verbs: dict[str, list[CicsVerb]] = {}
    for prog_name in transid_to_program.values():
        if prog_name in compiled_verbs:
            continue
        raw = cobol_sources.get(prog_name)
        if raw is None:
            compiled_verbs[prog_name] = []
            continue
        observer = _CollectingObserver(prog_name)
        spec = build_cics_spec(
            context_holder=[None],
            result_holder=[None],
            observer=observer,
        )
        # Positional args: source, parser, spec
        compile_cics_program(raw, parser, spec)
        compiled_verbs[prog_name] = observer.verbs

    return transid_to_program, compiled_verbs
