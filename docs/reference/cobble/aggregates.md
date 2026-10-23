# Domain aggregates (experimental)

Candidate domain aggregates: groups of fields that are read and written together, found by factoring
a field co-occurrence matrix. Three stages, each a separate command, run after the
[partition graph](partition.md) and a whole (not `--call-targets-only`) `cobble-dataflow-fixpoint`
run.

```text
cobble-experimental-aggregate-unify     --graph graph.jsonl --out unified.jsonl
cobble-experimental-aggregate-matrix    --defs defs.jsonl --extents extents.jsonl --unified unified.jsonl
                                        [--min-fields 3] [--min-occurrences 5] [--min-cooccurrences 3]
                                        --out-matrix matrix.npz --out-meta meta.json
cobble-experimental-aggregate-decompose --matrix matrix.npz --meta meta.json [--k 10,15,20,25,30]
                                        [--max-iter 500] [--seed 42] --out-dir DIR
```

## Unify

A field is a partition-graph node, `<program>:<record>.<field>`, so two programs' fields of one
name stay apart. Unify joins fields of different programs that hold one datum: field A and field B
are one class when every byte `i` of A lands on byte `i` of B and on no other byte of B, A and B are
the same size, and B is in another program. Bytes are followed along the graph's edge alignments,
relayed by `OCCURS` table occurrences: a commarea handed over into a linkage
byte table and moved out of it joins the caller's `CDEMO-USER-ID` to the callee's. A field that any
edge without known placement reaches, a clamped move, neither relays nor joins. Copies inside one
program never join. Classes are the connected components of the joined pairs; `unified.jsonl` holds
one `{"members": [...]}` per class, and the first member names it.

## Matrix

Each `defs.jsonl` row names the fields its range covers, through the extents, and the paragraphs of
its node and of every definer. Each field is replaced by its class. A paragraph keeps at least `--min-fields` fields, a field at least `--min-occurrences`
paragraphs, and a pair at least `--min-cooccurrences` shared paragraphs. Each kept pair scores its
positive PMI, `log2(n(a,b) * paragraphs / (n(a) * n(b)))`, in a symmetric sparse matrix;
`meta.json` lists the field of each row and the paragraphs counted.

## Decompose

Non-negative matrix factorisation at each `k`. Each factor lists its twenty highest-loading fields;
`report.json` recommends the `k` with the most factors whose fields span four or more name
prefixes.

## On CardDemo

Unify finds the commarea fields shared across the online programs, the date utility's parameters
under their callers' names, and the statement program's I/O area. At `k` 30 the factors are each
one program's working storage: the account-update and card-update programs' own commarea areas,
screen input fields, the export record (whose layouts overlay account, customer and transaction
fields), status and edit flags, and the shared commarea fields with each program's own. No factor
joins records of different files. Programs relate account, card and customer by key value through
the cross-reference file, which co-occurrence in paragraphs does not see.
