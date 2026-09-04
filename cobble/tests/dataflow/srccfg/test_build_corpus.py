"""One member's failure is a reported failure, not the end of a 3,779-member run.

The parse stage learned this the expensive way: an unguarded member aborted a run
that costs hours. A CFG pass over the cache is cheaper, but a run that dies on
member 40 still tells you nothing about the other 3,739.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import (
    asg_paths,
    build_corpus,
    build_one,
    cfg_from_dict,
    cfg_to_dict,
    main,
)
from cobble.dataflow.srccfg.config import SrcCfgConfig


def _asg(program: str) -> dict:
    return {
        "program_id": program,
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "MOVE",
                        "operands": [{"name": "'A'"}, {"name": "WS-FLAG-A"}],
                    }
                ],
            }
        ],
    }


def _cache(tmp_path: Path, *programs: str) -> Path:
    asg_dir = tmp_path / "parsed"
    asg_dir.mkdir(parents=True, exist_ok=True)
    for program in programs:
        (asg_dir / f"{program}.json").write_text(json.dumps(_asg(program)))
    return asg_dir


def test_the_cache_is_walked_in_a_stable_order(tmp_path: Path) -> None:
    """Sorted, so two runs produce diffable reports -- the report is read as a diff
    against the previous run to see whether a change moved the failure count."""
    asg_dir = _cache(tmp_path, "PROGB", "PROGA")

    assert [p.stem for p in asg_paths(asg_dir)] == ["PROGA", "PROGB"]


def test_a_non_json_file_in_the_cache_is_not_a_member(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, "PROGA")
    (asg_dir / "notes.txt").write_text("hello")

    assert [p.stem for p in asg_paths(asg_dir)] == ["PROGA"]


def test_one_member_builds_to_one_json_named_for_the_program(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, "PROGA")
    out_dir = tmp_path / "srccfg"

    result = build_one(asg_dir / "PROGA.json", out_dir)

    assert result.message == ""
    assert result.cfg_path == out_dir / "PROGA.json"
    assert json.loads(result.cfg_path.read_text())["program"] == "PROGA"


def test_the_written_json_carries_every_node_and_edge(tmp_path: Path) -> None:
    """The consumers of this file are later passes, so the round trip has to keep
    the node ids and the edge kinds -- those ARE the reaching condition."""
    asg_dir = _cache(tmp_path, "PROGA")

    written = json.loads(
        build_one(asg_dir / "PROGA.json", tmp_path / "out").cfg_path.read_text()
    )

    assert [node["id"] for node in written["nodes"]] == [
        "MAIN#label",
        "MAIN/0",
        "MAIN#end",
    ]
    assert {edge["kind"] for edge in written["edges"]} == {"FLOW"}


def test_a_member_that_does_not_parse_is_a_reported_failure(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, "PROGA")
    (asg_dir / "BROKEN.json").write_text("{ not json")

    results = build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    failed = [r for r in results if r.message]
    assert [r.member for r in failed] == ["BROKEN"]
    assert (tmp_path / "out" / "PROGA.json").exists()


def test_the_failure_message_names_the_member_and_says_what_happened(
    tmp_path: Path,
) -> None:
    asg_dir = _cache(tmp_path)
    (asg_dir / "BROKEN.json").write_text("{ not json")

    results = build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    assert results[0].message.startswith("BROKEN: ")


def test_a_failing_member_writes_no_partial_cfg(tmp_path: Path) -> None:
    """A half-written CFG is worse than none: the next pass cannot tell it from a
    member that genuinely has three nodes."""
    asg_dir = _cache(tmp_path)
    (asg_dir / "BROKEN.json").write_text("{ not json")

    build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    assert list((tmp_path / "out").glob("*.json")) == []


def test_the_cli_reports_counts_and_exits_zero_when_every_member_built(
    tmp_path: Path, caplog
) -> None:
    import logging

    caplog.set_level(logging.INFO)
    asg_dir = _cache(tmp_path, "PROGA", "PROGB")
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path}/out"\n')

    assert main(["--config", str(config)]) == 0
    assert "2" in caplog.text


def test_the_cli_exits_non_zero_when_any_member_failed(tmp_path: Path) -> None:
    """A pass whose output is consumed by later passes must not report success while
    silently missing members -- the next pass would read the gap as "this field is
    never written"."""
    asg_dir = _cache(tmp_path, "PROGA")
    (asg_dir / "BROKEN.json").write_text("{ not json")
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path}/out"\n')

    assert main(["--config", str(config)]) == 1


def test_the_cli_does_not_print_member_names_to_stdout(tmp_path: Path, capsys) -> None:
    """Member names are corpus identifiers. The failure report is a log record, so a
    run in a shared terminal does not leak them, and stdout stays free for a machine
    channel."""
    asg_dir = _cache(tmp_path, "PROGA")
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path}/out"\n')

    main(["--config", str(config)])

    assert capsys.readouterr().out == ""


def test_cfg_to_dict_is_json_serialisable_without_a_custom_encoder(
    tmp_path: Path,
) -> None:
    """Enums and frozen dataclasses are not JSON by themselves, and a default=str
    encoder would write "EdgeKind.TRUE" -- which no reader can round-trip."""
    from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, Edge, Node, NodeKind

    cfg = Cfg(
        program="PROGA",
        nodes=(Node(id="MAIN/0", kind=NodeKind.NOP, paragraph="MAIN"),),
        edges=(Edge(source="MAIN/0", target="MAIN/0", kind=EdgeKind.TRUE),),
    )

    assert json.loads(json.dumps(cfg_to_dict(cfg)))["edges"][0]["kind"] == "TRUE"


def _rebuilt(asg_dir: Path) -> None:
    """Rebuild a CFG from the ASG for comparison."""
    from cobble.dataflow.srccfg.build_corpus import _cfg_of

    return _cfg_of(asg_dir / "PROGA.json")


def test_a_written_cfg_reads_back_identical(tmp_path: Path) -> None:
    """The corpus call graph is built from the written files, so a lossy round trip
    would silently drop call sites -- and a missing call site reads as a member with
    no callees rather than as an error."""
    asg_dir = _cache(tmp_path, "PROGA")
    built = build_one(asg_dir / "PROGA.json", tmp_path / "out")

    assert cfg_from_dict(json.loads(built.cfg_path.read_text())) == _rebuilt(asg_dir)


# F8: two members can declare one PROGRAM-ID, and the output is named for the program


def _two_members_one_program(tmp_path: Path) -> Path:
    """MEMA and MEMB both declare PROGRAM-ID PROGA, which a real corpus does often."""
    asg_dir = tmp_path / "parsed"
    asg_dir.mkdir(parents=True, exist_ok=True)
    for member in ("MEMA", "MEMB"):
        (asg_dir / f"{member}.json").write_text(json.dumps(_asg("PROGA")))
    return asg_dir


def test_a_duplicate_program_id_does_not_overwrite_the_first_members_cfg(
    tmp_path: Path,
) -> None:
    """F8: the output file is named for the PROGRAM-ID, so the second member replaced
    the first. Both members then answered every query with one member's graph, and the
    run reported two successes -- the failure mode this pass is built to prevent, since
    a query about the overwritten member gets a confident answer from other code."""
    asg_dir = _two_members_one_program(tmp_path)

    results = build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    assert sorted(p.name for p in (tmp_path / "out").glob("*.json")) == [
        "PROGA.json",
        "PROGA__MEMB.json",
    ]
    assert [r.cfg_path.name for r in results] == ["PROGA.json", "PROGA__MEMB.json"]


def test_a_duplicate_program_id_is_reported_and_names_both_sides(
    tmp_path: Path,
) -> None:
    """A qualified file nobody is told about is a second silent failure: every consumer
    looks up PROGA.json, so the reader has to learn that a second member exists."""
    asg_dir = _two_members_one_program(tmp_path)

    results = build_corpus(SrcCfgConfig(asg_dir=asg_dir, out_dir=tmp_path / "out"))

    assert results[0].message == ""
    assert results[1].message.startswith("MEMB: PROGRAM-ID PROGA is already built")
    assert "PROGA__MEMB.json" in results[1].message


def test_a_name_collision_is_a_warning_and_not_a_failed_run(
    tmp_path: Path, caplog
) -> None:
    """The exit code answers one question -- is a member missing from the output -- and
    a collision is the case where none is. Counting it as a failure would train the
    reader to ignore a non-zero exit, which is what makes a real missing member
    invisible."""
    import logging

    caplog.set_level(logging.INFO)
    asg_dir = _two_members_one_program(tmp_path)
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path}/out"\n')

    assert main(["--config", str(config)]) == 0
    assert "1 name collision(s)" in caplog.text
    assert "0 failure(s)" in caplog.text
