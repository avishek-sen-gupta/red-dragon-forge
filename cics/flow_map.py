"""extract_transaction_flow_map() — static analysis builder API.

Compiles each CICS program referenced in a CSD, collects CICS verb events via
CicsFlowObserver, enriches them with BMS map field metadata, and returns a
JSON-serialisable list of transaction flow maps.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from bms_copybook_gen.models import BmsMapSet
from cics.flow_observer import CicsVerb, field_direction


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
            )
        )


def _enrich_verb(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> dict:  # type: ignore[type-arg]
    """Convert CicsVerb → JSON-serialisable dict with BMS field metadata."""
    entry: dict[str, Any] = {
        "verb": verb.verb,
        "program": verb.program,
        "map": verb.map_name,
        "mapset": verb.mapset_name,
        "xctl_target": verb.xctl_target,
        "transid": verb.transid,
        "fields": [],
    }
    if verb.mapset_name and verb.map_name and verb.verb in ("SEND_MAP", "RECEIVE_MAP"):
        mapset = bms_mapsets.get(verb.mapset_name)
        if mapset:
            bms_map = next((m for m in mapset.maps if m.label == verb.map_name), None)
            if bms_map:
                entry["fields"] = [
                    {"name": f.label, "direction": field_direction(f)}
                    for f in bms_map.fields
                ]
    return entry


def extract_transaction_flow_map(
    csd_source: str,
    bms_mapsets: dict[str, BmsMapSet],
    cobol_sources: dict[str, bytes],
    *,
    parser: Any = None,
) -> list[dict]:  # type: ignore[type-arg]
    """Static analysis: extract a JSON transaction flow map from a CICS project.

    Args:
        csd_source: CSD text with DEFINE TRANSACTION(...) PROGRAM(...) entries.
        bms_mapsets: parsed BmsMapSet models keyed by mapset name.
        cobol_sources: program name → raw (un-prepassed) COBOL bytes.
        parser: ProLeap parser instance.

    Returns:
        List of dicts, one per transaction, in CSD order.
    """
    from cics.dispatcher import parse_csd  # noqa: PLC0415
    from cics.bootstrap import compile_cics_program  # noqa: PLC0415
    from cics.strategy import CicsLoweringStrategy  # noqa: PLC0415
    from cics.preprocessor import apply_cics_prepass  # noqa: PLC0415

    # parse_csd expects a Path; write CSD text to a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    transid_to_program = parse_csd(csd_path)
    csd_path.unlink(missing_ok=True)

    # Compile each distinct program with its own observer
    compiled_verbs: dict[str, list[CicsVerb]] = {}
    for prog_name in transid_to_program.values():
        if prog_name in compiled_verbs:
            continue
        raw = cobol_sources.get(prog_name)
        if raw is None:
            compiled_verbs[prog_name] = []
            continue
        # compile_cics_program expects pre-passed bytes; apply the prepass here
        prepassed = apply_cics_prepass(raw.decode("utf-8", errors="replace")).encode()
        observer = _CollectingObserver(prog_name)
        strategy = CicsLoweringStrategy(
            context_holder=[None],
            result_holder=[None],
            observer=observer,
        )
        # Positional args: source, parser, strategy
        compile_cics_program(prepassed, parser, strategy)
        compiled_verbs[prog_name] = observer.verbs

    results: list[dict] = []  # type: ignore[type-arg]
    for transid, prog_name in transid_to_program.items():
        verbs = compiled_verbs.get(prog_name, [])
        results.append(
            {
                "transid": transid,
                "entry_program": prog_name,
                "flow": [_enrich_verb(v, bms_mapsets) for v in verbs],
            }
        )
    return results
