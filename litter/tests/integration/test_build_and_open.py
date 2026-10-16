"""A built package opens to the image its link list produced, and names any entry it cannot read."""

import json
import zipfile
from collections.abc import Mapping
from pathlib import Path

import pytest
from cobol_asg.cobol_parser import ProLeapCobolParser
from interpreter.project.cobol_compile import link_units
from interpreter.project.coprocessor_compile import lower_program
from litter.build import build
from litter.manifest import Manifest
from litter.open import open_package
from litter.package_error import PackageError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cbl"
LINKED_ENTRY = "image.linked.json"
MEMBER_NAME_MISMATCH = "String should match pattern '^[A-Z#@$][A-Z0-9#@$]{0,7}$'"


PROGRAMS = ("MAINPGM", "SUBPGM", "OTHERPGM")
LINKED = ("MAINPGM", "SUBPGM")


def _build(
    parser: ProLeapCobolParser,
    tmp_path: Path,
    mapsets: Mapping[str, Path],
    link: tuple[str, ...] = LINKED,
) -> Path:
    return build(
        name="app",
        programs=PROGRAMS,
        link=link,
        sources={name: FIXTURES / f"{name}.cbl" for name in PROGRAMS},
        parser=parser,
        specs=(),
        copybook_dirs=(),
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


def _lowered(parser: ProLeapCobolParser, work_dir: Path, name: str) -> Path:
    return lower_program(
        (FIXTURES / f"{name}.cbl").read_bytes(),
        parser=parser,
        specs=(),
        copybook_dirs=(),
        work_dir=work_dir,
        tolerant=False,
    )


def test_built_package_opens_to_the_image_its_link_list_produced(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    path = _build(parser, tmp_path, {})
    package = open_package(path)
    reference = tmp_path / "reference"
    linked = link_units(
        [_lowered(parser, reference, name) for name in LINKED], reference
    )

    assert (
        path,
        package.manifest,
        package.image,
        sorted(package.image.programs),
        dict(package.mapsets),
        list(_entries(path)),
        len(list((tmp_path / "work").glob("*.unit.json"))),
    ) == (
        tmp_path / "out" / "app.zip",
        Manifest(
            programs=LINKED,
            coprocessors=(),
            transactions=(),
            files=(),
            mapsets=(),
        ),
        linked,
        ["MAINPGM", "SUBPGM"],
        {},
        ["manifest.json", LINKED_ENTRY],
        3,
    )


@pytest.mark.parametrize(
    ("link", "fault"),
    [
        (("MAINPGM", "ABSENT"), "link names ABSENT, which programs does not list"),
        (("MAINPGM", "SUBPGM", "MAINPGM"), "link lists MAINPGM more than once"),
    ],
)
def test_build_refuses_a_link_list_it_cannot_link(
    parser: ProLeapCobolParser, tmp_path: Path, link: tuple[str, ...], fault: str
) -> None:
    with pytest.raises(PackageError) as refused:
        _build(parser, tmp_path, {}, link=link)

    assert (str(refused.value), list(tmp_path.iterdir())) == (
        f"{tmp_path / 'out' / 'app.zip'}: {fault}",
        [],
    )


def test_rebuild_reuses_the_work_directory(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    first = open_package(_build(parser, tmp_path, {})).image
    built = _ast_mtimes(tmp_path / "work")
    second = open_package(_build(parser, tmp_path, {})).image

    assert (len(built), _ast_mtimes(tmp_path / "work"), second) == (3, built, first)


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

    with pytest.raises(PackageError) as refused:
        open_package(path)

    assert str(refused.value) == (
        f"{path}: {LINKED_ENTRY}: not a linked-program file of format 3"
    )


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

    assert str(refused.value) == (
        f"{path}: manifest.json: coprocessors: Field required; "
        "transactions: Field required; files: Field required; mapsets: Field required"
    )


def test_open_refuses_an_unknown_manifest_key(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    path = _build(parser, tmp_path, {})
    manifest = Manifest.model_validate_json(_entries(path)["manifest.json"])
    unknown = {**manifest.model_dump(), "owner": "SOMEONE"}
    _rewrite(
        path,
        {**_entries(path), "manifest.json": json.dumps(unknown).encode("utf-8")},
    )

    with pytest.raises(PackageError) as refused:
        open_package(path)

    assert str(refused.value) == (
        f"{path}: manifest.json: owner: Extra inputs are not permitted"
    )


def test_open_refuses_a_program_name_that_is_a_path(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    linked = _entries(_build(parser, tmp_path, {}))[LINKED_ENTRY]
    names = (f"{tmp_path}/escape", "../../escape")
    manifest = {
        "programs": names,
        "coprocessors": [],
        "transactions": [],
        "files": [],
        "mapsets": [],
    }
    path = tmp_path / "crafted.zip"
    _rewrite(
        path,
        {
            "manifest.json": json.dumps(manifest).encode("utf-8"),
            LINKED_ENTRY: linked,
        },
    )

    with pytest.raises(PackageError) as refused:
        open_package(path)

    assert (
        str(refused.value),
        list(tmp_path.parent.rglob("escape.linked.json")),
    ) == (
        f"{path}: manifest.json: programs.0: {MEMBER_NAME_MISMATCH}; "
        f"programs.1: {MEMBER_NAME_MISMATCH}",
        [],
    )


def test_build_refuses_a_program_name_that_is_a_path(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    with pytest.raises(PackageError) as refused:
        build(
            name="app",
            programs=("../X",),
            link=("../X",),
            sources={},
            parser=parser,
            specs=(),
            copybook_dirs=(),
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
            transactions=(),
            files=(),
            mapsets={},
            tolerant=False,
        )

    assert (str(refused.value), list(tmp_path.iterdir())) == (
        f"{tmp_path / 'out' / 'app.zip'}: manifest.json: programs.0: "
        f"{MEMBER_NAME_MISMATCH}",
        [],
    )


def test_a_failed_build_leaves_no_package(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        _build(parser, tmp_path, {"ABSENT": tmp_path / "ABSENT.json"})

    assert list((tmp_path / "out").iterdir()) == []


def test_the_manifest_names_the_programs_the_image_holds(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    path = build(
        name="app",
        programs=("MISNAMED",),
        link=("MISNAMED",),
        sources={"MISNAMED": FIXTURES / "OTHERPGM.cbl"},
        parser=parser,
        specs=(),
        copybook_dirs=(),
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        transactions=(),
        files=(),
        mapsets={},
        tolerant=False,
    )

    package = open_package(path)

    assert (package.manifest.programs, tuple(package.image.programs)) == (
        ("OTHERPGM",),
        ("OTHERPGM",),
    )


def test_build_refuses_a_package_name_that_is_a_path(
    parser: ProLeapCobolParser, tmp_path: Path
) -> None:
    with pytest.raises(PackageError) as refused:
        build(
            name="../x",
            programs=("MAINPGM",),
            link=("MAINPGM",),
            sources={"MAINPGM": FIXTURES / "MAINPGM.cbl"},
            parser=parser,
            specs=(),
            copybook_dirs=(),
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
            transactions=(),
            files=(),
            mapsets={},
            tolerant=False,
        )

    assert (str(refused.value), list(tmp_path.iterdir())) == (
        f"{tmp_path / 'out'}: package name '../x': String should match pattern"
        " '^[A-Za-z0-9][A-Za-z0-9_.-]*$'",
        [],
    )
