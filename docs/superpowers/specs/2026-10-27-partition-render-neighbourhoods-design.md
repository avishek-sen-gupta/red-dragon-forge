# Partition render: a program map and one page per program

## Why

`cobble-experimental-partition-render` draws every field of the graph on one page. On a corpus of
3,764 programs and about 4 million fields it ran for over 1 h 45 min without finishing, and its
output would not load anyway: CardDemo's page is 7.2 MB for 15,851 nodes, about 450 bytes a node,
so a corpus page would be about 1.8 GB.

Measured and projected causes:

| cause | CardDemo | corpus, projected |
|---|---|---|
| each dataset slot scans every edge (`_ties`, `_among`) | 0.24 s, 263 slots | about 9 h |
| each program scans every edge (`_local`) and every node (`_programs`) | under 0.05 s | about 40 min |
| `read_graph` holds full Pydantic models, 1,322 bytes an item | 70 MB for a 13 MB file | about 25 GB |
| one page | 7.2 MB | about 1.8 GB |

## What it becomes

`--out` names a directory. The render writes:

- `index.html`: the **program map**. One node per program and one per dataset record; an edge
  between two of them when some field edge links their fields or slots, weighted by how many.
  Clicking a program opens its page. Search finds a program or dataset by name.
- `programs/<PROGRAM>.html`: today's page, drawn for one program's **neighbourhood** only.
- `scripts/graphology.umd.min.js`, `scripts/sigma.min.js`: written once; every page loads them by
  relative `src`, so 3,764 pages do not each carry 260 KB of script.

A program's neighbourhood is:

1. its own fields, origins and sinks;
2. every node one edge from those, in other programs or dataset slots;
3. for each dataset slot reached, every field one edge from that slot, so following a dataset still
   shows all of its writers and readers;

and every edge whose both ends are in the neighbourhood. On CardDemo the largest neighbourhood is
2,445 nodes (COACTUPC), the smallest 4 (COBSWAIT), and all 31 together are 27,392, 1.7× the graph.

The page per neighbourhood is today's page unchanged: the same fold, layout, panel and dataset
view. The program's own fields are drawn as now; a neighbour's fields keep their own program and
are laid out as that program's region, holding only the fields that touch this program.

## Reading

One streaming pass reads the graph into frozen, slotted dataclasses with interned strings, as unify's
reader does, with progress every tenth of the file. It keeps every attribute the page draws. Nodes
and edges are indexed once by program and by node, so a neighbourhood is gathered from its own
nodes' edges, never from a scan of the whole graph. Each neighbourhood becomes a `FieldGraph` just
before its page is drawn, and is dropped after its page is written.

## Fixes inside a page

Inside a neighbourhood the per-slot and per-program scans still grow as slots × edges. Each is
replaced by one pass that indexes edges by node; the output is unchanged, which the existing page
tests check.

## Logging

One line per page at every tenth of the programs, with that page's node count, and the time the map
took.

## Not doing

- A view of unify's classes or decompose's factors. It could later link from the map.
- A record-level map.
- Splitting a neighbourhood that is still too big to draw. The largest is reported in the log.

## Builder's calls

- The map lays out by a seeded networkx `spring_layout`, weighted by link count, like today's program
  placement.
- Program names become file names as they are; COBOL program names are already file-safe.
- `make partition-render` writes the directory where it wrote `partition.html` before.
