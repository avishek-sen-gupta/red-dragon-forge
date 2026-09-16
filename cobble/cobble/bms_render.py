"""Render BMS maps as 3270 screens, as text or HTML.

    uv run cobble-bms-render --config config/carddemo.toml --out-dir out-screens
    uv run cobble-bms-render --config config/carddemo.toml --map COSGN0A \\
        --values turn1.json turn2.json --format html --out-dir out-screens

Without --values every map in the corpus renders with its INITIAL text only.
Each --values file is one SEND MAP payload, ``{"map": NAME, "fields": {BASE:
VALUE}}`` -- the shape cicada's screen channel carries -- and renders to a file
named after it. Cursor position, attribute overrides and DATAONLY/MAPONLY sends
are not in that payload, so they are not rendered.
"""

from __future__ import annotations

import argparse
import html
import itertools
import json
import logging
import operator
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from bms_copybook_gen.parser import _parse_attrb
from cobble.bms_metadata import _resolve_config, _run_hlasm_export, _strip_quotes
from cobble.cli_logging import configure_cli_logging
from cobble.matching_files import matching_files
from cobble.path_utils import ensure_dir

logger = logging.getLogger(__name__)

_PAIR = re.compile(r"\(\s*(\d+)\s*,\s*(\d+)\s*\)")
_DEFAULT_SIZE = (24, 80)
_BLANK = (" ", "")


@dataclass(frozen=True)
class ScreenField:
    name: str
    row: int
    col: int
    length: int
    initial: str
    attrb: tuple[str, ...]
    color: str


@dataclass(frozen=True)
class ScreenMap:
    name: str
    rows: int
    cols: int
    fields: tuple[ScreenField, ...]


def _size(raw: str) -> tuple[int, int]:
    m = _PAIR.match(raw)
    return (int(m.group(1)), int(m.group(2))) if m else _DEFAULT_SIZE


def _position(raw: str, cols: int) -> tuple[int, int]:
    """POS is (line,column), or a zero-based offset into the screen buffer."""
    m = _PAIR.match(raw)
    if m:
        return int(m.group(1)), int(m.group(2))
    offset = int(raw) if raw.strip().isdigit() else 0
    return offset // cols + 1, offset % cols + 1


def _screen_field(inv: Mapping, cols: int) -> ScreenField:
    args = inv.get("args", {})
    row, col = _position(args.get("POS", ""), cols)
    return ScreenField(
        name=inv.get("label") or "",
        row=row,
        col=col,
        length=int(args.get("LENGTH", 0)),
        initial=_strip_quotes(args["INITIAL"]) if "INITIAL" in args else "",
        attrb=tuple(_parse_attrb(args["ATTRB"])) if "ATTRB" in args else (),
        color=args.get("COLOR", ""),
    )


def _screen_map(mdi: Mapping, body: Sequence[Mapping]) -> ScreenMap:
    rows, cols = _size(mdi.get("args", {}).get("SIZE", ""))
    return ScreenMap(
        name=mdi.get("label") or "",
        rows=rows,
        cols=cols,
        fields=tuple(
            _screen_field(inv, cols) for inv in body if inv.get("name") == "DFHMDF"
        ),
    )


def map_layouts(invocations: Sequence[Mapping]) -> tuple[ScreenMap, ...]:
    """One ScreenMap per DFHMDI, holding every DFHMDF up to the next DFHMDI."""
    starts = tuple(
        i for i, inv in enumerate(invocations) if inv.get("name") == "DFHMDI"
    )
    ends = (*starts[1:], len(invocations))
    return tuple(
        _screen_map(invocations[s], invocations[s + 1 : e])
        for s, e in zip(starts, ends, strict=True)
    )


def layouts_from_bms(bms_path: Path, macros_dir: Path) -> tuple[ScreenMap, ...]:
    data = _run_hlasm_export(bms_path, macros_dir)
    return map_layouts(data.get("macro_invocations", []))


def _shown_text(field: ScreenField, values: Mapping[str, str]) -> str:
    """Only the characters BMS actually sends: a field with no data writes its
    attribute byte and nothing else, leaving whatever is already on screen."""
    raw = values.get(field.name, field.initial) if field.name else field.initial
    visible = "" if "DRK" in field.attrb else raw
    return visible[: field.length]


def _style(field: ScreenField) -> str:
    colour = f"c-{field.color.lower() or 'default'}"
    flags = tuple(
        css
        for flag, css in (("BRT", "brt"), ("UNPROT", "unprot"))
        if flag in field.attrb
    )
    return " ".join((colour, *flags))


def _cells(
    screen_map: ScreenMap, values: Mapping[str, str]
) -> Mapping[tuple[int, int], tuple[str, str]]:
    """(row, col) -> (char, css class); later fields overwrite earlier ones, and
    each field's attribute byte blanks the cell before its data."""
    placements = (
        ((f.row - 1, f.col - 1 + i), (ch, _style(f) if i else ""))
        for f in screen_map.fields
        for i, ch in enumerate(" " + _shown_text(f, values))
    )
    return {
        cell: content
        for cell, content in placements
        if 0 <= cell[0] < screen_map.rows and 0 <= cell[1] < screen_map.cols
    }


def _row(
    cells: Mapping[tuple[int, int], tuple[str, str]], row: int, cols: int
) -> tuple[tuple[str, str], ...]:
    return tuple(cells.get((row, col), _BLANK) for col in range(cols))


def render_text(screen_map: ScreenMap, values: Mapping[str, str]) -> str:
    cells = _cells(screen_map, values)
    return "".join(
        "".join(ch for ch, _ in _row(cells, r, screen_map.cols)) + "\n"
        for r in range(screen_map.rows)
    )


_SCREEN_CSS = """
body { background: #111; margin: 0; padding: 1rem; }
pre.bms3270 { background: #000; color: #3f3; font: 16px/1.25 "IBM Plex Mono",
  Menlo, Consolas, monospace; padding: 1ch; margin: 0; display: inline-block;
  border: 2px solid #333; border-radius: 6px; }
.c-default, .c-green { color: #3f3; } .c-blue { color: #69f; }
.c-red { color: #f55; } .c-yellow { color: #ff5; } .c-pink { color: #f7f; }
.c-turquoise { color: #5ff; } .c-neutral { color: #eee; }
.brt { font-weight: bold; filter: brightness(1.3); }
.unprot { text-decoration: underline; text-decoration-color: #3f36; }
"""


def _html_run(css: str, chars: str) -> str:
    text = html.escape(chars, quote=False)
    return f'<span class="{css}">{text}</span>' if css else text


def _html_row(row: tuple[tuple[str, str], ...]) -> str:
    return "".join(
        _html_run(css, "".join(ch for ch, _ in run))
        for css, run in itertools.groupby(row, operator.itemgetter(1))
    )


def render_html(screen_map: ScreenMap, values: Mapping[str, str]) -> str:
    cells = _cells(screen_map, values)
    body = "\n".join(
        _html_row(_row(cells, r, screen_map.cols)) for r in range(screen_map.rows)
    )
    title = html.escape(screen_map.name)
    return (
        f"<!doctype html>\n<html><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{_SCREEN_CSS}</style></head>\n"
        f'<body><pre class="bms3270">{body}</pre></body></html>\n'
    )


_RENDERERS = {"text": (render_text, ".txt"), "html": (render_html, ".html")}


@dataclass(frozen=True)
class _Job:
    map_name: str
    values: Mapping[str, str]
    stem: str


def _payload_job(path: Path, map_override: str) -> _Job:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _Job(
        map_name=map_override or payload.get("map", ""),
        values=payload.get("fields", {}),
        stem=path.stem,
    )


def _jobs(
    args: argparse.Namespace, layouts: Mapping[str, ScreenMap]
) -> tuple[_Job, ...]:
    if args.values:
        return tuple(_payload_job(Path(p), args.map) for p in args.values)
    names = (args.map,) if args.map else tuple(layouts)
    return tuple(_Job(map_name=n, values={}, stem=n) for n in names)


def _all_layouts(config_path: Path) -> Mapping[str, ScreenMap]:
    config = _resolve_config(config_path)
    sources = sorted(matching_files(config.bms_dir, config.bms_globs))
    return {
        m.name: m for src in sources for m in layouts_from_bms(src, config.macros_dir)
    }


def _write_job(
    job: _Job, layouts: Mapping[str, ScreenMap], fmt: str, out: Path
) -> bool:
    if job.map_name not in layouts:
        logger.error("error: no BMS map named %r", job.map_name)
        return False
    render, suffix = _RENDERERS[fmt]
    target = out / f"{job.stem}{suffix}"
    target.write_text(render(layouts[job.map_name], job.values), encoding="utf-8")
    logger.info("wrote %s", target)
    return True


def _parse_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", required=True, type=Path, help="TOML with [bms].")
    parser.add_argument("--map", default="", help="Render only this map (DFHMDI).")
    parser.add_argument(
        "--values", nargs="*", default=[], help="SEND MAP payload JSON files."
    )
    parser.add_argument("--format", choices=tuple(_RENDERERS), default="text")
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    configure_cli_logging()
    args = _parse_cli()
    layouts = _all_layouts(args.config)
    ensure_dir(args.out_dir)
    written = tuple(
        _write_job(job, layouts, args.format, args.out_dir)
        for job in _jobs(args, layouts)
    )
    return 0 if all(written) else 1


if __name__ == "__main__":
    raise SystemExit(main())
