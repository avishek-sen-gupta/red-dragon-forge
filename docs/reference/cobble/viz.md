# cobble: views and screens

HTML views over the graph file, CFG files and path traces, and the BMS screen tools. The
knowledge-graph renderers are in [knowledge-graph](knowledge-graph.md); the CFG renderers are in
[srccfg](srccfg.md).

Code: `cobble/cobble/viz/`, `cobble/cobble/bms_metadata.py`, `cobble/cobble/bms_render.py`.

## cobble-viz-callgraph

```
cobble-viz-callgraph --graph GRAPH --cfg CFG --out OUT
```

The program-level call graph as `call-dep.json`. `--graph` is the file `cobble-build` wrote;
`--cfg` is a `cobble-srccfg-build` file, which supplies the program list.

## cobble-viz-sequence

```
cobble-viz-sequence --cfg CFG --out OUT [--entry PROGRAM]
```

Writes `sequences.json` with two parts: the cross-program CICS `LINK` calls in order, walked
from the entry program, and each program's `PERFORM` tree with `LINK`s as leaf steps.
`--entry` defaults to the first program in the CFG file.

## cobble-viz-render

```
cobble-viz-render --input INPUT --mode {callgraph,top,program} --out OUT [--program PROGRAM]
```

| Mode | Input | Draws |
|---|---|---|
| `callgraph` | `call-dep.json` | vis.js force-directed graph of cross-program calls |
| `top` | `sequences.json` | Mermaid sequence diagram of cross-program calls |
| `program` | `sequences.json` | Mermaid sequence diagram of one program's `PERFORM` tree; needs `--program` |

Program labels drop the longest uppercase prefix common to every program. The page loads vis.js
or Mermaid from a CDN (forge-y0e).

## cobble-bms-metadata

```
cobble-bms-metadata --config CONFIG [--output FILE]
```

One JSONL record per BMS source: mapset, maps, and each named field with position, length,
attributes, and the screen label from a preceding unlabelled `DFHMDF` with `INITIAL` text.
Reads the corpus config's `[bms]` table and runs `hlasm_export`. Writes to stdout by default.
A relative `macros_dir` resolves against `cobble/` (red-dragon-forge-jy9).

## cobble-bms-render

```
cobble-bms-render --config CONFIG --out-dir OUT_DIR [--map MAP] [--values FILE ...] [--format {text,html}]
```

| Flag | Meaning |
|---|---|
| `--config` | a config with `[bms]` |
| `--out-dir` | output directory. Required |
| `--map` | render only this map (`DFHMDI` name) |
| `--values` | `SEND MAP` payload files, `{"map": NAME, "fields": {BASE: VALUE}}`; each renders to a file named after it |
| `--format` | `text` (default) or `html` |

Without `--values` each map renders with its `INITIAL` text only. Cursor position, attribute
overrides and `DATAONLY`/`MAPONLY` are not rendered.
