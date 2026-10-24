# Domain aggregates (experimental)

Candidate domain aggregates: groups of fields that are read and written together, found by factoring
a field co-occurrence matrix. Three stages, each a separate command, run after the
[partition graph](partition.md) and a whole (not `--call-targets-only`) `cobble-dataflow-fixpoint`
run.

```text
cobble-experimental-aggregate-unify     --graph graph.jsonl --out unified.jsonl
cobble-experimental-aggregate-matrix    --defs defs.jsonl --extents extents.jsonl --unified unified.jsonl
                                        [--min-fields 3] [--min-occurrences 4] [--min-cooccurrences 3]
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
its node and of every definer. Each field is replaced by its class, and a table element's
occurrences that unify left apart count as the one declared field, `WS-TRAN-NUM` for every
`WS-TRAN-NUM(i,j)`. A paragraph keeps at least `--min-fields` fields, a field at least `--min-occurrences`
paragraphs, and a pair at least `--min-cooccurrences` shared paragraphs. Each kept pair scores its
positive PMI, `log2(n(a,b) * paragraphs / (n(a) * n(b)))`, in a symmetric sparse matrix;
`meta.json` lists the field of each row and the paragraphs counted.

## Decompose

Rounds of non-negative matrix factorisation, one per `--min-occurrences` and `--k` pair; the
thresholds must strictly decrease. Round 1 factors the matrix's rows and columns for the fields
written in at least its threshold of paragraphs into its `k` factors. Each later round takes the
fields its own threshold admits, subtracts what all earlier rounds' factors rebuild of that part of
the matrix, clips at zero, and factors what is left. Cutting rows and columns gives exactly the
matrix the matrix stage would have built at that threshold, since the threshold only drops fields;
so the matrix stage runs once, at the lowest threshold, and `meta.json` records each field's
paragraph count and the threshold it was built at. A round below that threshold is refused: it
would see no more fields. Matrices saved before these fields existed do not load; rebuild them.

`rounds.json` holds one entry per round: its threshold, the share of its part of the matrix that
earlier rounds already explained (`explained_by_earlier`), and its fit: `k`, reconstruction error,
iterations, and each factor's twenty highest-loading fields with the name prefixes they span.

## On CardDemo

With dataset links in the graph (see [partition](partition.md)), unify joins each record's fields
across the programs that read and write its file, batch and online alike. At `k` 30 the account,
transaction, user, card and customer records each come out as one factor spanning the programs that
use them (the account record six, the transaction and user records five), the transaction-category
balance record joins its two batch programs, and the card programs' shared commarea is a factor of
its own. The customer record's fields are written in four paragraphs each, which is why the default
`--min-occurrences` is 4: at 5 the whole record is cut before factoring. A single round at a lower
threshold adds working-storage mixtures, not records; a second round, below, does better. The card cross-reference record joins across eight
programs but forms no factor: its fields are only read, in too few paragraphs to factor.

Built at `--min-occurrences 2` and decomposed with `--min-occurrences 4 2 --k 30 10`, round 1 gives
those factors and explains 92% of the looser matrix; round 2 adds the daily transaction feed and the
statement program's transaction record, each one program's own, the rest of the user record, and
the transaction and user list screens' rows, alongside file-status and error-message storage.
