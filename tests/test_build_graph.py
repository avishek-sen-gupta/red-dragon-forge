"""The run-level failure guards: one bad member must not abort a corpus run,
and what was skipped must be impossible to miss in the output."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

from cobble.build_graph import (
    RULE,
    _failure_report_lines,
    _file_control_failures,
    _load_transid_to_program,
    _report_failures,
    _tally_lines,
)
from cobble.corpus_config import DEFAULT_COPYBOOK_EXTENSIONS, CorpusConfig
from cobble.interpreter.cobol.ast_store import AstStore


def _config(tmp_path: Path, **overrides) -> CorpusConfig:
    defaults = dict(
        cobol_dir=tmp_path / "cbl",
        cobol_globs=("*.cbl",),
        jcl_dir=tmp_path / "jcl",
        jcl_globs=("*.jcl",),
        proclib_dirs=(),
        csd_files=(),
        copybook_dirs=(tmp_path / "cpy",),
        copybook_extensions=DEFAULT_COPYBOOK_EXTENSIONS,
        out_dir=tmp_path / "out",
    )
    return CorpusConfig(**{**defaults, **overrides})


def _touch(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_csd_that_does_not_parse_does_not_abort_the_run(tmp_path: Path) -> None:
    """``_load_transid_to_program`` ran before the writer opened and did not guard
    ``parse_csd``, so a malformed CSD killed the whole run — even though the corpus
    index already guards the very same file."""
    broken = _touch(tmp_path / "csd" / "BROKEN.CSD", "this is not a DEFINE\n")

    read = _load_transid_to_program(_config(tmp_path, csd_files=(broken,)))

    assert dict(read.transid_to_program) == {}
    assert len(read.failures) == 1
    assert read.failures[0].startswith("CSD BROKEN.CSD: ")


def test_a_good_csd_still_loads_alongside_a_broken_one(tmp_path: Path) -> None:
    good = _touch(
        tmp_path / "csd" / "GOOD.CSD",
        "DEFINE TRANSACTION(CC00) PROGRAM(COSGN00C) GROUP(CARDDEMO)\n",
    )
    broken = _touch(tmp_path / "csd" / "BROKEN.CSD", "this is not a DEFINE\n")

    read = _load_transid_to_program(_config(tmp_path, csd_files=(broken, good)))

    assert dict(read.transid_to_program) == {"CC00": "COSGN00C"}
    assert len(read.failures) == 1


def test_the_failure_report_says_the_output_is_incomplete() -> None:
    """The report used to be a quiet stdout line after "Wrote ...", easy to scroll
    past on a corpus where 62 members are missing from a graph that otherwise looks
    finished."""
    lines = _failure_report_lines(["index JCL A.jcl: boom", "JCL B.jcl: boom"])

    assert lines[2] == "!!  2 FAILURE(S) -- THIS GRAPH IS INCOMPLETE"
    assert lines[-3:] == (
        "  - index JCL A.jcl: boom",
        "  - JCL B.jcl: boom",
        RULE,
    )


def test_the_failure_report_tallies_by_category() -> None:
    """62 lines of detail hide the shape. The tally is what a reader acts on.

    Commonest category first, ties by name — so a corpus whose problem is one
    kind of member reads as one line, not as sixty-two.
    """
    assert _tally_lines(
        [
            "index JCL A.jcl: boom",
            "index JCL B.jcl: boom",
            "JCL C.jcl: boom",
            "CSD D.CSD: boom",
        ]
    ) == (
        "      2  index JCL",
        "      1  CSD",
        "      1  JCL",
    )


def test_the_report_is_logged_whole_and_at_error_level(capsys, caplog) -> None:
    """One record, not one per line: a handler that prefixes or timestamps each
    record must not interleave anything through the middle of the report. ERROR
    because it says the artifact just written is wrong, which is not progress
    information -- a caller that raises the level to hide the per-stage counts
    still has to see this."""
    caplog.set_level(logging.INFO)
    failures = ["index JCL A.jcl: boom"]

    _report_failures(failures)

    assert caplog.messages == ["\n".join(_failure_report_lines(failures))]
    assert caplog.records[0].levelno == logging.ERROR
    assert capsys.readouterr() == ("", "")


def test_no_failures_logs_no_report(caplog) -> None:
    caplog.set_level(logging.INFO)
    _report_failures([])
    assert caplog.messages == []


# ── the FILE-CONTROL stage's own ASG construction ────────────────


class _CannedBridge:
    """An AsgJsonParser that writes one canned ASG, so no JVM is needed."""

    def __init__(self, asg: Mapping) -> None:
        self._asg = asg

    def parse_to_file(self, source: bytes, out: Path) -> None:
        out.write_text(json.dumps(self._asg), encoding="utf-8")


class _NoFilePaths:
    """The one thing the file-graph extractor asks of the corpus index."""

    def resolve_file_path(self, kind, node_id):
        return None


class _CollectingWriter:
    def __init__(self) -> None:
        self.nodes: tuple = ()
        self.edges: tuple = ()

    def add_all(self, nodes, edges) -> None:
        self.nodes = (*self.nodes, *nodes)
        self.edges = (*self.edges, *edges)


def _asg_with(coprocessor_statement: Mapping) -> dict:
    """A batch program with one FILE-CONTROL entry, an OPEN, and one
    coprocessor statement the base dispatch table does not know."""
    return {
        "program_id": "SOMEPROG",
        "file_control": [{"file_name": "CUST-FILE", "assign_to": "CUSTDD"}],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "OPEN",
                        "mode_groups": [{"mode": "INPUT", "files": ["CUST-FILE"]}],
                    },
                    coprocessor_statement,
                ],
            }
        ],
    }


def _run_file_control(
    tmp_path: Path, asg: Mapping
) -> tuple[tuple[str, ...], _CollectingWriter]:
    store = AstStore(tmp_path / "cache")
    path = tmp_path / "cbl" / "SOMEPROG.cbl"
    store.parse_all({path: b""}, _CannedBridge(asg))
    writer = _CollectingWriter()
    return _file_control_failures(path, store, _NoFilePaths(), writer), writer


def test_file_control_reads_a_member_containing_exec_cics(tmp_path: Path) -> None:
    """The stage built its ASGs with no dialect parser registered.

    ``_dialect_parsers`` is a ContextVar defaulting to empty; the CICS flow stage
    sets it around its own parse, this stage never did. So every member with an
    EXEC CICS block -- 2,129 of 3,779 on the onboarding corpus -- failed here with
    ``Unknown COBOL statement type: 'EXEC_CICS'`` and contributed nothing, not even
    its PROGRAM node.
    """
    failures, writer = _run_file_control(
        tmp_path,
        _asg_with({"type": "EXEC_CICS", "exec_cics_text": "EXEC CICS RETURN END-EXEC"}),
    )

    assert failures == ()
    assert [(edge.source, edge.target) for edge in writer.edges] == [
        ("SOMEPROG", "CUSTDD")
    ]


def test_file_control_reads_a_member_containing_exec_sql(tmp_path: Path) -> None:
    """Same defect, second coprocessor: a batch program with embedded SQL and no
    CICS at all failed here too, and no CSD could ever route it elsewhere."""
    failures, writer = _run_file_control(
        tmp_path,
        _asg_with({"type": "EXEC_SQL", "exec_sql_text": "EXEC SQL COMMIT END-EXEC"}),
    )

    assert failures == ()
    assert [(edge.source, edge.target) for edge in writer.edges] == [
        ("SOMEPROG", "CUSTDD")
    ]
