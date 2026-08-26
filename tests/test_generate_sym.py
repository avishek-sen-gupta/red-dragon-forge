"""BMS map-source selection for generate_sym.

Which files in bms_dir are BMS maps is corpus shape: CardDemo ships *.bms,
one production corpus ships every member as .txt with non-map JCL sitting in
the same directory, so the selector has to be a glob rather than a fixed
extension.
"""

from pathlib import Path

from cobble.corpus_config import BmsConfig
from cobble.generate_sym import _bms_sources


def _config(tmp_path: Path, globs: tuple[str, ...]) -> BmsConfig:
    return BmsConfig(
        bms_dir=tmp_path,
        bms_globs=globs,
        macros_dir=Path("bms-macros"),
        sym_dir=tmp_path / "sym",
    )


def test_bms_sources_selects_only_files_matching_the_configured_globs(
    tmp_path: Path,
) -> None:
    (tmp_path / "MAP001.txt").write_text("")
    (tmp_path / "MAP002.txt").write_text("")
    (tmp_path / "$COBMAP.txt").write_text("")  # compile JCL, not a map

    assert _bms_sources(_config(tmp_path, ("MAP*.txt",))) == [
        tmp_path / "MAP001.txt",
        tmp_path / "MAP002.txt",
    ]


def test_bms_sources_defaults_to_the_bms_extension(tmp_path: Path) -> None:
    (tmp_path / "COACTUP.bms").write_text("")
    (tmp_path / "README.txt").write_text("")

    assert _bms_sources(_config(tmp_path, ("*.bms",))) == [tmp_path / "COACTUP.bms"]


def test_bms_sources_deduplicates_files_matched_by_several_globs(
    tmp_path: Path,
) -> None:
    (tmp_path / "MAP001.txt").write_text("")

    assert _bms_sources(_config(tmp_path, ("MAP*.txt", "*.txt"))) == [
        tmp_path / "MAP001.txt"
    ]
