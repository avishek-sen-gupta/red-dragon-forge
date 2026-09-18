"""Extract structured metadata from BMS screen maps via hlasm_export.

    uv run cobble-bms-metadata --config config/prod.local.toml
    uv run cobble-bms-metadata --config config/prod.local.toml --output out.jsonl

For each BMS map source, emits one JSONL record with mapset name, map names,
and every named field with its position, length, attributes, and -- when a
preceding unlabeled DFHMDF carries a text INITIAL -- the screen label the
operator sees next to the field.

Uses cicada's bms_copybook_gen.parser for the DFHMSD/DFHMDI/DFHMDF structure,
then enriches with INITIAL and POS from the raw hlasm_export invocations.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import json
import logging
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from bms_copybook_gen.parser import parse_mapsets
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import BmsConfig, load_bms_config
from cobble.matching_files import matching_files
from cobble.path_utils import ensure_parent

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HLASM = (
    _REPO_ROOT.parent
    / "cicada"
    / "third-party"
    / "che-che4z-lsp-for-hlasm-fork"
    / "build"
    / "bin"
    / "hlasm_export"
)

_EMPTY = ""


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def _strip_quotes(s: str) -> str:
    stripped = s.strip()
    return (
        stripped[1:-1]
        if stripped.startswith("'") and stripped.endswith("'")
        else stripped
    )


def _parse_pos(raw: str) -> tuple[int, int] | tuple[()]:
    m = re.match(r"\((\d+),(\d+)\)", raw)
    return (int(m.group(1)), int(m.group(2))) if m else ()


def _is_label_text(initial: str) -> bool:
    """True if an INITIAL value looks like a screen label rather than a placeholder."""
    return bool(
        initial
        and not all(c in "X0$." for c in initial.replace(" ", ""))
        and not all(c in "=-_* " for c in initial)
    )


# ---------------------------------------------------------------------------
# field record: frozen, no Optional — _EMPTY sentinel for absent strings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FieldRecord:
    name: str
    length: int
    attrb: str
    pos: tuple[int, int] | tuple[()]
    initial: str
    picout: str
    screen_label: str
    grpname: str
    occurs: int


def _field_to_dict(f: _FieldRecord) -> Mapping:
    base = {"name": f.name, "length": f.length, "attrb": f.attrb}
    optional = {
        k: v
        for k, v in (
            ("pos", list(f.pos) if f.pos else _EMPTY),
            ("initial", f.initial),
            ("picout", f.picout),
            ("screen_label", f.screen_label),
            ("grpname", f.grpname),
            ("occurs", f.occurs if f.occurs else _EMPTY),
        )
        if v and v != _EMPTY
    }
    return {**base, **optional}


# ---------------------------------------------------------------------------
# stateful fold over invocations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FoldState:
    fields: tuple[_FieldRecord, ...]
    pending_label: str
    in_map: bool


def _make_field_record(
    label: str,
    args: Mapping,
    initial: str,
    pending: str,
    bms_field_map: MappingProxyType,
) -> _FieldRecord:
    bms_f = bms_field_map.get(label)
    picout_raw = args.get("PICOUT", "")
    return _FieldRecord(
        name=label,
        length=int(args.get("LENGTH", 0)),
        attrb=args.get("ATTRB", ""),
        pos=_parse_pos(args.get("POS", "")),
        initial=initial,
        picout=_strip_quotes(picout_raw) if picout_raw else _EMPTY,
        screen_label=pending,
        grpname=bms_f.grpname if bms_f else _EMPTY,
        occurs=bms_f.occurs if bms_f else 0,
    )


def _fold_dfhmdf(
    field_labels: frozenset[str],
    bms_field_map: MappingProxyType,
    state: _FoldState,
    inv: Mapping,
) -> _FoldState:
    args = inv.get("args", {})
    label = inv.get("label", "")
    initial = _strip_quotes(args["INITIAL"]) if "INITIAL" in args else _EMPTY

    if not label:
        return _FoldState(
            fields=state.fields,
            pending_label=initial if _is_label_text(initial) else state.pending_label,
            in_map=True,
        )
    if label not in field_labels:
        return state
    rec = _make_field_record(label, args, initial, state.pending_label, bms_field_map)
    return _FoldState(fields=(*state.fields, rec), pending_label=_EMPTY, in_map=True)


def _fold_inv(
    field_labels: frozenset[str],
    bms_field_map: MappingProxyType,
    map_label: str,
    state: _FoldState,
    inv: Mapping,
) -> _FoldState:
    """Reduce one hlasm invocation into the accumulator."""
    name = inv.get("name", "")
    if name == "DFHMDI":
        return _FoldState(
            fields=state.fields,
            pending_label=_EMPTY,
            in_map=inv.get("label") == map_label,
        )
    if name != "DFHMDF" or not state.in_map:
        return state
    return _fold_dfhmdf(field_labels, bms_field_map, state, inv)


def _extract_fields_for_map(
    invocations: Sequence[Mapping], bms_map
) -> tuple[_FieldRecord, ...]:
    field_labels = frozenset(f.label for f in bms_map.fields)
    bms_field_map = MappingProxyType({f.label: f for f in bms_map.fields})
    initial_state = _FoldState(fields=(), pending_label=_EMPTY, in_map=False)
    final = functools.reduce(
        lambda st, inv: _fold_inv(field_labels, bms_field_map, bms_map.label, st, inv),
        invocations,
        initial_state,
    )
    return final.fields


# ---------------------------------------------------------------------------
# single-file extraction
# ---------------------------------------------------------------------------


def run_hlasm_export(bms_path: Path, macros_dir: Path) -> Mapping:
    result = subprocess.run(
        [str(_HLASM), str(bms_path), "--syslib", str(macros_dir)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def _map_record(invocations: Sequence[Mapping], bms_map) -> Mapping:
    return {
        "map_name": bms_map.label,
        "fields": tuple(
            _field_to_dict(f) for f in _extract_fields_for_map(invocations, bms_map)
        ),
    }


def extract_one(bms_path: Path, macros_dir: Path) -> Mapping:
    """Extract metadata from one BMS map file."""
    data = run_hlasm_export(bms_path, macros_dir)
    invocations = data.get("macro_invocations", [])
    mapsets = parse_mapsets(invocations)

    return {
        "type": "bms",
        "mapset": mapsets[0].label if mapsets else _EMPTY,
        "source_file": str(bms_path),
        "maps": tuple(
            _map_record(invocations, bms_map)
            for mapset in mapsets
            for bms_map in mapset.maps
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_config(config_path: Path) -> BmsConfig:
    config = load_bms_config(config_path)
    if config.macros_dir.is_absolute():
        return config
    return BmsConfig(
        bms_dir=config.bms_dir,
        bms_globs=config.bms_globs,
        macros_dir=_REPO_ROOT / config.macros_dir,
        sym_dir=config.sym_dir,
    )


def _relative_source(bms_path: Path, bms_dir: Path) -> str:
    with contextlib.suppress(ValueError):
        return str(bms_path.resolve().relative_to(bms_dir.resolve()))
    return str(bms_path)


def _extract_and_relativize(bms_path: Path, config: BmsConfig) -> Mapping:
    record = extract_one(bms_path, config.macros_dir)
    return {**record, "source_file": _relative_source(bms_path, config.bms_dir)}


def _try_extract(bms_path: Path, config: BmsConfig) -> tuple[Mapping, ...]:
    try:
        return (_extract_and_relativize(bms_path, config),)
    except (json.JSONDecodeError, subprocess.SubprocessError, OSError) as exc:
        logger.error("error: %s: %s", bms_path.name, exc)
        return ()


def _write_output(records: tuple[Mapping, ...], output_path: str) -> None:
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    ensure_parent(Path(output_path)).write_text(f"{text}\n" if text else "")


def _parse_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Corpus TOML config with [bms] section.",
    )
    parser.add_argument(
        "--output", metavar="FILE", help="Write JSONL here instead of stdout."
    )
    return parser.parse_args()


def _jsonl_text(records: tuple[Mapping, ...]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"


def _emit(records: tuple[Mapping, ...], output: str, source_count: int) -> None:
    failures = source_count - len(records)
    if output:
        _write_output(records, output)
        logger.info(
            "%d maps extracted, %d failures, wrote %s",
            len(records),
            failures,
            output,
        )
    else:
        sys.stdout.write(_jsonl_text(records))
        logger.info("%d maps extracted, %d failures", len(records), failures)


def main() -> int:
    configure_cli_logging()
    args = _parse_cli()
    config = resolve_config(args.config)
    sources = sorted(matching_files(config.bms_dir, config.bms_globs))
    per_file = tuple(_try_extract(p, config) for p in sources)
    records = tuple(r for batch in per_file for r in batch)
    _emit(records, args.output, len(sources))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
