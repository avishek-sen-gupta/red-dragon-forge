# Domain aggregates (experimental)

Candidate domain aggregates: groups of fields that are read and written together, and the
paragraphs that use them, found by factoring a paragraph x field matrix. Three stages, each a separate command, run after the
[partition graph](partition.md) and a whole (not `--call-targets-only`) `cobble-dataflow-fixpoint`
run.

```text
cobble-experimental-aggregate-unify     --graph graph.jsonl --out unified.jsonl
cobble-experimental-aggregate-matrix    --defs defs.jsonl --extents extents.jsonl --unified unified.jsonl
                                        [--min-occurrences 4] [--exclude REGEX ...]
                                        --out-matrix matrix.npz --out-meta meta.json
cobble-experimental-aggregate-decompose --matrix matrix.npz --meta meta.json
                                        --min-occurrences N [N ...] --k K [K ...]
                                        [--max-iter 500] [--seed 42] --out-dir DIR
```

## Unify

A field is a partition-graph node, `<program>:<record>.<field>`, so two programs' fields of one
name stay apart. Unify joins fields of different programs that hold one datum: field A and field B
are one class when every byte `i` of A lands on byte `i` of B and on no other byte of B, A and B are
the same size, and B is in another program. Bytes are followed along the graph's edge alignments,
relayed by `OCCURS` table occurrences: a commarea handed over into a linkage
byte table and moved out of it joins the caller's `CDEMO-USER-ID` to the callee's. Dataset slots
relay the same way, over `exact` dataset edges only (see [partition](partition.md)): a writer's
field and a reader's field, or two readers' fields, that cover the same bytes of one dataset record,
at the same offsets and the same size, are one class: a file no COBOL program writes still joins
its readers. A `possible` dataset edge has no placement and is ignored; it
never stops a field joining through its other edges. A field that any
edge without known placement reaches, a clamped move, neither relays nor joins. Copies inside one
program never join. Classes are the connected components of the joined pairs; `unified.jsonl` holds
one `{"members": [...]}` per class, and the first member names it.

## Matrix

Each `defs.jsonl` row names the fields its range covers, through the extents, and the paragraphs of
its node and of every definer. A field whose own `PROGRAM:RECORD.PATH` name any `--exclude` pattern
matches is left out there, before unify's classes apply, so a class loses only its matching members.
Each remaining field is replaced by its class, and a table element's occurrences that unify left
apart count as the one declared field, `WS-TRAN-NUM` for every `WS-TRAN-NUM(i,j)`. Every paragraph
that touches a field is a row, and a field with at least `--min-occurrences` paragraphs is a
column, 1 where the paragraph touches the field; nothing
is counted in pairs, so a field seen in two paragraphs has a column like any other. `meta.json`
lists the paragraph of each row, the field of each column and each field's paragraph count.

## Decompose

Rounds of non-negative matrix factorisation, one per `--min-occurrences` and `--k` pair; the
thresholds must strictly decrease. Round 1 factors the matrix's columns for the fields written in at
least its threshold of paragraphs into its `k` factors. Each factor has a loading per field, what the
candidate aggregate is made of, and a loading per paragraph, where it is used. Each later round takes the
fields its own threshold admits, subtracts what all earlier rounds' factors rebuild of that part of
the matrix, clips at zero, and factors what is left. Cutting columns gives exactly the
matrix the matrix stage would have built at that threshold, since the threshold only drops fields;
so the matrix stage runs once, at the lowest threshold, and `meta.json` records each field's
paragraph count and the threshold it was built at. A round below that threshold is refused: it
would see no more fields. Matrices saved before these fields existed do not load; rebuild them.

`rounds.json` holds one entry per round: its threshold, the share of its part of the matrix that
earlier rounds already explained (`explained_by_earlier`), and its fit: `k`, reconstruction error,
iterations, and each factor's twenty highest-loading fields with the name prefixes they span and
its twenty highest-loading paragraphs.

## On CardDemo

With dataset links in the graph (see [partition](partition.md)), unify joins each record's fields
across the programs that read and write its file, batch and online alike. Built at
`--min-occurrences 2` and decomposed with `--min-occurrences 4 2 --k 30 10`, round 1 gives the
account, customer, transaction, card, user, transaction-category balance, daily transaction and
statement transaction records, each with the paragraphs that read or write it, and the card
cross-reference record appears for the first time; about a third of its factors are one program's
working storage: `FILLER` runs, file-status pairs, map fields, commareas, message and edit areas.
Round 2 adds what only two or three paragraphs touch: the import program's export record, the list
screens' rows, the statement program's customer fields.

Excluding those by name, here `FILLER_n`, file status, `WS-MISC-STORAGE`, messages, CICS response
codes, edit flags, BMS map fields and commareas, leaves 139 fields at threshold 4, too few for 30
factors; at `--k 15 10` each record but the user record, which splits in two, is one factor, the
account record across all five programs that use it, and the cross-reference record joins the
account and transaction records in the bill-payment and posting paragraphs.
