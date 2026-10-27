# Domain aggregates (experimental)

Candidate domain aggregates: groups of fields that are read and written together, and the
paragraphs that use them, found by factoring a paragraph x field matrix. Three stages, each a separate command, run after the
[partition graph](partition.md) and a `cobble-dataflow-fixpoint`
run.

```text
cobble-experimental-aggregate-unify     --graph graph.jsonl [--join-unplaced] --out unified.jsonl
cobble-experimental-aggregate-matrix    --defs defs.jsonl --extents extents.jsonl --unified unified.jsonl
                                        [--exclude REGEX ...]
                                        --out-matrix matrix.npz --out-meta meta.json
cobble-experimental-aggregate-decompose --matrix matrix.npz --meta meta.json
                                        --min-occurrences N [N ...] --k K [K ...]
                                        [--max-iter 500] [--seed 42] --out-dir DIR
cobble-experimental-aggregate-class-share --matrix matrix.npz --meta meta.json --unified unified.jsonl
                                          --graph graph.jsonl --min-occurrences N [N ...]
cobble-experimental-aggregate-scorecard --matrix matrix.npz --meta meta.json --unified unified.jsonl
                                        --min-occurrences N [N ...] --k K [K ...]
                                        [--max-iter 500] [--seed 42]
```

`class-share` and `scorecard` are diagnostics, not stages: they read the matrix and the classes and change nothing.

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
copy without known placement reaches, a clamped move, neither relays nor joins. An edge marked
`rebuilt` does not count: arithmetic or STRING building the field's value in place leaves it the
datum it was, so `ADD … TO ACCT-CURR-BAL` keeps the balance in its class. `--join-unplaced` lifts
that rule: such a field still relays and joins through its placed edges, and the unplaced edge is
ignored. On CardDemo it adds 54 members across 16 classes (90 classes become 92), commarea fields
of another program joining classes they already belonged to in the others. Copies inside one
program never join. Classes are the connected components of the joined pairs; `unified.jsonl` holds
one `{"members": [...]}` per class, and the first member names it.

Unify reads the graph a line at a time and keeps only each field's and slot's id, program, size and
subscripts and each edge's ends and alignments, logging progress every tenth of the file's lines.

## Matrix

Each `defs.jsonl` row names the fields its range covers, through the extents, and the paragraphs of
its node and of every definer. A field whose own `PROGRAM:RECORD.PATH` name any `--exclude` pattern
matches is left out there, before unify's classes apply, so a class loses only its matching members.
Each remaining field is replaced by its class, and a table element's occurrences that unify left
apart count as the one declared field, `WS-TRAN-NUM` for every `WS-TRAN-NUM(i,j)`. Every paragraph
that touches a field is a row and every field a paragraph touches is a column, 1 where the
paragraph touches the field; nothing is counted in pairs, so a field seen in one paragraph has a
column like any other. `meta.json`
lists the paragraph of each row, the field of each column and each field's paragraph count.

## Decompose

Rounds of non-negative matrix factorisation, one per `--min-occurrences` and `--k` pair; the
thresholds must strictly decrease. Round 1 factors the matrix's columns for the fields written in at
least its threshold of paragraphs into its `k` factors. Each factor has a loading per field, what the
candidate aggregate is made of, and a loading per paragraph, where it is used. Each later round takes the
fields its own threshold admits, subtracts what all earlier rounds' factors rebuild of that part of
the matrix, clips at zero, and factors what is left. Factors never go negative, so what is left is
zero wherever the matrix is: the rebuild is computed only at the matrix's entries and the matrix
stays sparse, so memory grows with its entries, not with paragraphs times fields. The matrix holds every field, so the
thresholds live in decompose alone: each round cuts the columns of the fields `meta.json` counts in
at least its threshold of paragraphs. Matrices saved before this layout do not load; rebuild them.

`rounds.json` holds one entry per round: its threshold, the share of its part of the matrix that
earlier rounds already explained (`explained_by_earlier`), and its fit: `k`, reconstruction error,
iterations, and each factor's twenty highest-loading fields with the name prefixes they span and
its twenty highest-loading paragraphs.

## Class share

For each `--min-occurrences` threshold, `class-share` logs the columns decompose would factor, how
many of them are unified classes, and the classes' share of those columns' entries. A small share
means the factors are dominated by fields only one program holds, and few classes reach a factor's
top fields. On CardDemo, at thresholds 10, 4 and 2, it reports 33 of 107, 75 of 462 and 80 of 904
columns as classes, holding 33.8%, 19.2% and 15.0% of the entries.

It then reads the partition graph and counts the fields dataset slots link, by what kept each out of
a class: the graph's field and slot counts and its `exact` and `possible` dataset edges, the
`possible` ones counted per reason, most common first (an edge with two reasons counts under both);
the fields
an `exact`, placed edge links to a slot, split into those in a class, those blocked because some
edge without placement reaches them, and the rest, whose layouts do not line up byte for byte with
another program's; and the fields only `possible` edges link. No slots means the graph was built
without `--knowledge-graph`. On CardDemo: 263 slots, 653 exact and 350 possible dataset edges, 312 of them for
`overlapping-layouts`, 31 for `no-step` and 7 for `dd-unbound`; of
470 fields linked by exact edges, 335 are in a class, 1 is blocked and 134 are neither; 100 fields
are linked only by possible edges.

## Scorecard

`scorecard` runs decompose's rounds with the same arguments and logs, per round, a headline and the
axes of its factors' quality, none of which needs labels:

| Score | What it measures |
|---|---|
| held-out AUC (headline) | hide 10% of the round's entries, fit on the rest, and rank each hidden entry against an empty cell of its paragraph's own program, a class counting for every program its members are in: 0.5 is chance, 1.0 is perfect, `nan` when no paragraph has an empty cell in its own program |
| fidelity | the fit's reconstruction error over the size of what it factored: 0 rebuilds it exactly |
| coverage | the share of entries inside some factor's top fields x top paragraphs |
| stability | refit on four random 90% samples of the paragraphs, match factors one to one, and average their cosine similarity |
| distinctness | the largest cosine similarity between two factors: low means separate aggregates |
| focus | the median share of a factor's field loading in its top 20 fields |
| reach | the share of factors whose top fields span two or more programs, a class counting every program its members are in, and the median programs spanned |
| class share | the classes' share of the round's entries, as `class-share` reports it |

Empty cells come from the paragraph's own program because a corpus matrix is close to one block per
program: an empty cell drawn from anywhere is almost always another program's field, and ranking a real
entry above that is easy, so the AUC would reward one factor per program. On CardDemo, with
`--min-occurrences 4 2 --k 30 10`, round 1 scores AUC 0.891 (0.979 against empty cells from anywhere),
fidelity 0.310, coverage 70.2%, stability 0.976, distinctness 0.553, focus 1.000, reach 76.7% (median 6.5
programs), class share 19.3%; round 2 scores AUC 0.437 and coverage 15.4%. A matrix of 3,000 programs whose
paragraphs touch their own program's fields at random scores AUC 0.499, where empty cells from anywhere
would have rated it highly.

## On CardDemo

With dataset links in the graph (see [partition](partition.md)), unify joins each record's fields
across the programs that read and write its file, batch and online alike. Decomposed with
`--min-occurrences 4 2 --k 30 10`, round 1 gives the
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
