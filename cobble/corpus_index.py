"""CorpusIndex — resolves (NodeKind, id) -> FileLocation once per run, from
the same CorpusConfig build_graph.py already loads.

Built before any extractor runs, so every node-construction call site
(across the JCL, CALL/COPY, CICS-flow and batch-file extractors, plus
GraphWriter's own defensive endpoint-stub synthesis) resolves a given node's
file_path identically no matter which extractor or what order constructs it
first. That determinism is what lets GraphWriter stream nodes the same way
it already streams edges, instead of buffering everything in memory to merge
whichever occurrence happened to carry the real file_path (see
knowledge_graph/graph_writer.py).

Node kinds fall into three groups:
  - Genuinely file-based (PROGRAM, COPYBOOK, JOB, STEP, INSTREAM_DATA,
    BMS_MAP): resolved by matching against the corpus's own naming
    conventions (filename stem == program-id, JCL step ownership, proclib
    .prc files, ...). A miss is UNRESOLVED — worth logging, since the corpus
    should have the file.
  - CSD-defined (TRANSACTION, CICS_FILE): resolved against config.csd_files
    when present; NO_DEFINITION_SOURCE when there's no CSD entry (or no CSD
    configured at all) for this corpus.
  - Structurally not file-based (DATASET, COBOL_FILE): always
    NOT_FILE_BASED. A DATASET's physical name is referenced from many DDs
    across possibly many JCL files; a COBOL_FILE's DD name is, per the
    (kind, id) identity model, shared by whichever programs happen to use
    the same ASSIGN TO name in their FILE-CONTROL — neither has a single
    file it is "defined" in.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from cobble.corpus_config import CorpusConfig
from cobble.file_location import FileLocation, FileLocationReason, NoFileLocation
from cobble.interpreter.project.graph_types import NodeKind
from cobble.matching_files import matching_files
from cobble.jackal.dsn import InStreamDSN
from cobble.jackal.jcl.parser import parse_jcl
from cobble.jackal.jcl.proc_expand import expand_procs
from cobble.jackal.jcl_graph import step_proc_provenance

logger = logging.getLogger(__name__)

_NOT_FILE_BASED = NoFileLocation(FileLocationReason.NOT_FILE_BASED)
_NO_DEFINITION_SOURCE = NoFileLocation(FileLocationReason.NO_DEFINITION_SOURCE)
_UNRESOLVED = NoFileLocation(FileLocationReason.UNRESOLVED)


def _proc_file(name: str, proclib_dirs: Sequence[Path]) -> Path | None:
    for proclib_dir in proclib_dirs:
        candidate = proclib_dir / f"{name}.prc"
        if candidate.is_file():
            return candidate
    return None


class CorpusIndex:
    def __init__(self, config: CorpusConfig) -> None:
        self._programs: dict[str, Path] = {}
        self._copybooks: dict[str, Path] = {}
        self._jobs: dict[str, Path] = {}
        self._steps: dict[str, Path] = {}
        self._instream: dict[str, Path] = {}
        self._bms_maps: dict[str, Path] = {}
        self._transactions: dict[str, Path] = {}
        self._cics_files: dict[str, Path] = {}
        self._build(config)

    def _build(self, config: CorpusConfig) -> None:
        for path in matching_files(config.cobol_dir, config.cobol_globs):
            self._programs.setdefault(path.stem.upper(), path)

        for copybook_dir in config.copybook_dirs:
            if not copybook_dir.is_dir():
                continue
            for path in sorted(copybook_dir.iterdir()):
                if path.is_file():
                    self._copybooks.setdefault(path.stem.upper(), path)

        for path in matching_files(config.jcl_dir, config.jcl_globs):
            self._index_jcl_file(path, config.proclib_dirs)

        for csd_file in config.csd_files:
            self._index_csd_file(csd_file)

        # bms_dir isn't part of CorpusConfig today (see BmsConfig) — BMS_MAP
        # resolution is left UNRESOLVED until that's threaded through too.

    def _index_jcl_file(self, path: Path, proclib_dirs: tuple[Path, ...]) -> None:
        try:
            job = parse_jcl(path.read_text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("CorpusIndex: JCL %s failed to parse: %s", path.name, exc)
            return

        job_name = job.name.upper()
        self._jobs.setdefault(job_name, path)

        expanded_job = expand_procs(job, proclib_dirs) if proclib_dirs else job
        proc_of_step = step_proc_provenance(job, expanded_job) if proclib_dirs else {}

        for step in expanded_job.steps:
            step_name = step.name.upper()
            proc_name = proc_of_step.get(step_name)
            step_file = _proc_file(proc_name, proclib_dirs) if proc_name else path
            step_file = step_file or path
            step_id = f"{job_name}.{step_name}"
            self._steps.setdefault(step_id, step_file)
            for dd in step.dds:
                if isinstance(dd.dsn, InStreamDSN):
                    instream_id = f"{step_id}.{dd.ddname.upper()}"
                    # Instream content is literal text in the JCL source itself,
                    # even when the step is proc-expanded — a PROC can't carry
                    # DD * content of its own, only DD overrides.
                    self._instream.setdefault(instream_id, path)

    def _index_csd_file(self, csd_file: Path) -> None:
        from cobble.cics.csd_parse import parse_csd, parse_csd_files

        try:
            for transid in parse_csd(csd_file):
                self._transactions.setdefault(transid.upper(), csd_file)
            for file_name in parse_csd_files(csd_file):
                self._cics_files.setdefault(file_name.upper(), csd_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CorpusIndex: CSD %s failed to parse: %s", csd_file.name, exc
            )

    def _get_or_warn(
        self, mapping: dict[str, Path], kind: NodeKind, node_id: str
    ) -> FileLocation:
        result = mapping.get(node_id)
        if result is not None:
            return result
        logger.warning(
            "CorpusIndex: %s %r not found in corpus — UNRESOLVED", kind.value, node_id
        )
        return _UNRESOLVED

    def resolve_file_path(self, kind: NodeKind, node_id: str) -> FileLocation:
        node_id = node_id.upper()
        match kind:
            case NodeKind.PROGRAM:
                return self._get_or_warn(self._programs, kind, node_id)
            case NodeKind.COPYBOOK:
                return self._get_or_warn(self._copybooks, kind, node_id)
            case NodeKind.JOB:
                return self._get_or_warn(self._jobs, kind, node_id)
            case NodeKind.STEP:
                return self._get_or_warn(self._steps, kind, node_id)
            case NodeKind.INSTREAM_DATA:
                return self._get_or_warn(self._instream, kind, node_id)
            case NodeKind.BMS_MAP:
                # Not indexed yet (bms_dir isn't part of CorpusConfig today —
                # see _build) — always UNRESOLVED by construction, not a
                # per-corpus problem worth warning about individually.
                return _UNRESOLVED
            case NodeKind.TRANSACTION:
                return self._transactions.get(node_id, _NO_DEFINITION_SOURCE)
            case NodeKind.CICS_FILE:
                return self._cics_files.get(node_id, _NO_DEFINITION_SOURCE)
            case NodeKind.DATASET | NodeKind.COBOL_FILE:
                # DATASET: a physical dataset name referenced from many DDs
                # across possibly many JCL files. COBOL_FILE: a DD name from
                # a program's FILE-CONTROL — per the (kind, id) identity
                # model, the same DD name from two different programs merges
                # into one node, so there is no single owning program's file
                # to attribute it to either.
                return _NOT_FILE_BASED
