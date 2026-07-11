import json
import sys
from pathlib import Path

import pytest

from cobble import canonical_export


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n" if rows else "")


def _write_config(tmp_path: Path, out_dir: Path) -> Path:
    config_path = tmp_path / "carddemo.yaml"
    config_path.write_text(
        "corpus:\n"
        f"  cobol_dir: {tmp_path}\n"
        '  cobol_globs: ["*.cbl"]\n'
        f"  jcl_dir: {tmp_path}\n"
        '  jcl_globs: ["*.jcl"]\n'
        '  copybook_dirs: []\n'
        f"  out_dir: {out_dir}\n"
    )
    return config_path


def test_main_reads_config_out_dir_and_writes_manifest_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_jsonl(out_dir / "nodes.jsonl", [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    _write_jsonl(out_dir / "edges.jsonl", [])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(sys, "argv", ["canonical_export", "--config", str(config_path)])
    exit_code = canonical_export.main()

    assert exit_code == 0
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["nodes"][0]["id"] == "PROGRAM::A"


def test_main_defaults_project_name_to_config_stem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_jsonl(out_dir / "nodes.jsonl", [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    _write_jsonl(out_dir / "edges.jsonl", [])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(sys, "argv", ["canonical_export", "--config", str(config_path)])
    canonical_export.main()

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["nodes"][0]["additional_properties"]["project_name"] == "carddemo"


def test_main_accepts_explicit_project_name_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_jsonl(out_dir / "nodes.jsonl", [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    _write_jsonl(out_dir / "edges.jsonl", [])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(
        sys, "argv",
        ["canonical_export", "--config", str(config_path), "--project-name", "custom-name"],
    )
    canonical_export.main()

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["nodes"][0]["additional_properties"]["project_name"] == "custom-name"


def test_main_returns_1_if_nodes_jsonl_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Only write edges.jsonl, not nodes.jsonl
    _write_jsonl(out_dir / "edges.jsonl", [])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(sys, "argv", ["canonical_export", "--config", str(config_path)])
    exit_code = canonical_export.main()

    assert exit_code == 1
    assert not (out_dir / "manifest.json").exists()
    captured = capsys.readouterr()
    assert "not found" in captured.err
    assert "make build" in captured.err


def test_main_returns_1_if_edges_jsonl_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Only write nodes.jsonl, not edges.jsonl
    _write_jsonl(out_dir / "nodes.jsonl", [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(sys, "argv", ["canonical_export", "--config", str(config_path)])
    exit_code = canonical_export.main()

    assert exit_code == 1
    assert not (out_dir / "manifest.json").exists()
    captured = capsys.readouterr()
    assert "not found" in captured.err
    assert "make build" in captured.err
