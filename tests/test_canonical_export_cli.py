import json
import sys
from pathlib import Path

import pytest

from cobble import canonical_export


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n" if rows else "")


def test_main_reads_explicit_paths_and_writes_manifest_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    output_path = tmp_path / "manifest.json"
    _write_jsonl(
        nodes_path, [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}]
    )
    _write_jsonl(edges_path, [])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "canonical_export",
            "--nodes",
            str(nodes_path),
            "--edges",
            str(edges_path),
            "--output",
            str(output_path),
            "--project-name",
            "carddemo",
        ],
    )
    exit_code = canonical_export.main()

    assert exit_code == 0
    assert output_path.exists()
    manifest = json.loads(output_path.read_text())
    assert manifest["nodes"][0]["id"] == "PROGRAM::A"


def test_main_requires_explicit_project_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    output_path = tmp_path / "manifest.json"
    _write_jsonl(
        nodes_path, [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}]
    )
    _write_jsonl(edges_path, [])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "canonical_export",
            "--nodes",
            str(nodes_path),
            "--edges",
            str(edges_path),
            "--output",
            str(output_path),
        ],
    )
    with pytest.raises(SystemExit):
        canonical_export.main()

    captured = capsys.readouterr()
    assert "--project-name" in captured.err


def test_main_writes_given_project_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    output_path = tmp_path / "manifest.json"
    _write_jsonl(
        nodes_path, [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}]
    )
    _write_jsonl(edges_path, [])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "canonical_export",
            "--nodes",
            str(nodes_path),
            "--edges",
            str(edges_path),
            "--output",
            str(output_path),
            "--project-name",
            "custom-name",
        ],
    )
    canonical_export.main()

    manifest = json.loads(output_path.read_text())
    assert (
        manifest["nodes"][0]["additional_properties"]["project_name"] == "custom-name"
    )


def test_main_returns_1_if_nodes_jsonl_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    output_path = tmp_path / "manifest.json"
    # Only write edges.jsonl, not nodes.jsonl
    _write_jsonl(edges_path, [])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "canonical_export",
            "--nodes",
            str(nodes_path),
            "--edges",
            str(edges_path),
            "--output",
            str(output_path),
            "--project-name",
            "carddemo",
        ],
    )
    exit_code = canonical_export.main()

    assert exit_code == 1
    assert not output_path.exists()
    captured = capsys.readouterr()
    assert "not found" in captured.err
    assert "make build" in captured.err


def test_main_returns_1_if_edges_jsonl_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    output_path = tmp_path / "manifest.json"
    # Only write nodes.jsonl, not edges.jsonl
    _write_jsonl(
        nodes_path, [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}]
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "canonical_export",
            "--nodes",
            str(nodes_path),
            "--edges",
            str(edges_path),
            "--output",
            str(output_path),
            "--project-name",
            "carddemo",
        ],
    )
    exit_code = canonical_export.main()

    assert exit_code == 1
    assert not output_path.exists()
    captured = capsys.readouterr()
    assert "not found" in captured.err
    assert "make build" in captured.err
