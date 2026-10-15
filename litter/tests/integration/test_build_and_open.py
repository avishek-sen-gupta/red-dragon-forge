"""A built package opens to the programs the compile produced, and names any entry it cannot read."""

import zipfile
from collections.abc import Mapping
from pathlib import Path

import pytest
from cobol_asg.cobol_parser import ProLeapCobolParser
from interpreter.project.coprocessor_compile import compile_program
from litter.build import build
from litter.manifest import Manifest
from litter.open import open_package
from litter.package_error import PackageError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cbl"
LINKED_ENTRY = "programs/MAINPGM.linked.json"


def _build(
    parser: ProLeapCobolParser, tmp_path: Path, mapsets: Mapping[str, Path]
) -> Path:
    return build(
        name="app",
        programs=("MAINPGM",),
        sources={"MAINPGM": FIXTURES / "MAINPGM.cbl"},
        parser=parser,
        specs=(),
        search_dirs=(FIXTURES,),
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        transactions=(),
        files=(),
        mapsets=mapsets,
        tolerant=False,
    )


def _entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _rewrite(path: Path, entries: Mapping[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def _ast_mtimes(work_dir: Path) -> dict[Path, int]:
    return {ast: ast.stat().st_mtime_ns for ast in work_dir.glob("**/*.ast.json")}


def test_built_package_opens_to_the_compiled_programs(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    path = _build(parser, tmp_path, {})
    package = open_package(path)
    compiled = compile_program(
        (FIXTURES / "MAINPGM.cbl").read_bytes(),
        parser,
        (),
        source_search_dirs=(FIXTURES,),
    )

    assert (
        path,
        package.manifest,
        dict(package.programs),
        dict(package.mapsets),
        list(_entries(path)),
    ) == (
        tmp_path / "out" / "app.zip",
        Manifest(
            programs=("MAINPGM",),
            coprocessors=(),
            transactions=(),
            files=(),
            mapsets=(),
        ),
        {"MAINPGM": compiled},
        {},
        ["manifest.json", LINKED_ENTRY],
    )


def test_rebuild_reuses_the_work_directory(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    first = open_package(_build(parser, tmp_path, {})).programs
    built = _ast_mtimes(tmp_path / "work")
    second = open_package(_build(parser, tmp_path, {})).programs

    assert (len(built), _ast_mtimes(tmp_path / "work"), dict(second)) == (
        2,
        built,
        dict(first),
    )


def test_open_names_a_missing_entry(parser: ProLeapCobolParser, tmp_path: Path) -> None:
    path = _build(parser, tmp_path, {})
    _rewrite(path, {n: d for n, d in _entries(path).items() if n != LINKED_ENTRY})

    with pytest.raises(PackageError) as refused:
        open_package(path)

    assert str(refused.value) == f"{path}: {LINKED_ENTRY}: missing"


def test_open_names_an_unreadable_linked_file(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    path = _build(parser, tmp_path, {})
    _rewrite(path, {**_entries(path), LINKED_ENTRY: b'{"format": 1, "linked": {}}'})
    prefix = f"{path}: {LINKED_ENTRY}: "
    suffix = ": not a linked-program file of format 2"

    with pytest.raises(PackageError) as refused:
        open_package(path)

    message = str(refused.value)
    assert (message[: len(prefix)], message[-len(suffix) :]) == (prefix, suffix)


def test_mapsets_ship_unchanged(parser: ProLeapCobolParser, tmp_path: Path) -> None:
    text = '{"mapset": "COSGN00", "maps": [{"name": "COSGN0A"}]}\n'
    exported = tmp_path / "COSGN00.json"
    exported.write_text(text, encoding="utf-8")

    package = open_package(_build(parser, tmp_path, {"COSGN00": exported}))

    assert (package.manifest.mapsets, dict(package.mapsets)) == (
        ("COSGN00",),
        {"COSGN00": text},
    )


def test_open_names_an_invalid_manifest(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    path = _build(parser, tmp_path, {})
    _rewrite(path, {**_entries(path), "manifest.json": b'{"programs": []}'})

    with pytest.raises(PackageError) as refused:
        open_package(path)

    assert str(refused.value).splitlines()[0] == (
        f"{path}: manifest.json: 4 validation errors for Manifest"
    )
