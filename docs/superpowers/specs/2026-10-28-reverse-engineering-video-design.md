# Reverse-engineering video — design

## Intent

A recorded video, roughly an hour (not fixed), for people new to reverse engineering legacy
systems. It shows the tools and techniques of the deterministic half of a reverse-engineering
pipeline on a real COBOL/CICS system (CardDemo), and where an LLM fits on top of it.

The one idea viewers should leave with: **let deterministic tools establish the facts about the
code — its syntax tree, control flow, data flow, how fields cluster — and have the LLM interpret
those facts, rather than guess from raw source.** The runtime half makes the same point: tests
drive the real application headlessly and assert on data at each stage.

## Audience

Newcomers to reverse engineering. They may know programming but not COBOL, CICS, compilers or
program analysis. Every technical term (AST, CFG, data-flow analysis, fixpoint, NMF) is explained
when it first appears, with a concrete CardDemo example, before its output is shown.

## Goals

- An overall narrative that carries the one idea from the opening to the close.
- A script per segment: what is on screen, the talking points, and the exact commands to run.
- Recordings of the user invoking the pipeline stage by stage — the steps `make carddemo-all`
  runs, one at a time — and showing each stage's rendered result.
- Short explainers, placed where each stage's output first appears:
  - AST — after parsing;
  - CFG — after the CFG build;
  - data-flow analysis and why it matters ("where did this value come from, and where does it
    go?") — before the fixpoint, which is introduced as the means to that end;
  - NMF and why it is useful (fields that travel together suggest the system's entities) —
    with the aggregates.
- The existing headless CardDemo tests, shown asserting on data at various stages.
- A brief shot of CardDemo actually running (its 3270 screens), which shows off RedDragon without
  making it the subject.
- An agent skill that answers questions about CardDemo **from the generated artifacts**, deducing
  answers rather than reading code. Source is quoted only to confirm a conclusion, minimally.

## Non-goals

- Not a RedDragon or forge feature tour. RedDragon appears only as "the app really runs".
- Not a COBOL tutorial beyond what each example needs.
- No new pipeline features built for the video. If a stage's output is unclear on camera, the fix
  is in the script or the explainer, not in cobble.

## Anti-goals

- An LLM shown reading raw COBOL and "explaining" it — that is the approach the video argues
  against.
- Implying the tools are complete. Where an answer needs judgement (see Q2 below), the video says
  so; that is where the LLM earns its place.
- Any client or proprietary identifiers anywhere. CardDemo only.

## Shape (segments)

Recorded as separate segments and edited together. Order:

1. **Opening — the problem.** Legacy code nobody fully understands; why reading it raw is slow
   and why "just ask an LLM" is unreliable (it reads names, not facts).
2. **The pipeline, stage by stage**, each stage run on camera and its result shown:
   parse (AST) → extents (byte layout) → fixpoint (data flow) → combine (cross-program links) →
   knowledge graph → CFG → partition graph and its pages → aggregates (field classes, matrix, NMF,
   scorecard). Explainers sit where listed under Goals. The stage list and commands come from
   `tools/rebuild-all.sh`.
3. **Runtime evidence.** The headless CardDemo tests driving transactions and asserting on data;
   a short clip of the real CardDemo screens under RedDragon.
4. **Interpretation — the agent skill** answering two questions from the artifacts:
   - **Q1:** "Where does the current balance on the account-view screen come from, and which
     programs can change it?" Tested: answerable from artifacts alone — screen metadata gives the
     field, a backward trace reaches the account file read, the partition graph puts the CICS file
     and the batch DDs on one dataset, and its writers are the interest, posting, bill-pay and
     account-update programs.
   - **Q2:** "If the card number widens from 16 to 19 digits, what breaks?" Tested: answerable
     from artifacts with judgement — a byte-exact walk over the partition graph, checked hop by hop
     against the links, the fixpoint's writer rows, the extents (REDEFINES) and the knowledge
     graph, finds ~90 places across ~21 programs and 8 files, including copies a name search misses
     (e.g. a commarea field named for a transaction that carries a card number). Known limits to
     show honestly: files with several record layouts, a table written through a computed
     subscript, and key lookups (not data flow).
5. **Close.** Back to the one idea.

## Existing material to build on

- `docs/presentation/` — a reveal.js deck with committed artifacts, and capture scripts under
  `docs/presentation/capture/`:
  - `headless.sh` — the headless CardDemo test runs (cicada sign-on and menu; forge on Db2);
  - `carddemo_3270_video.sh` + `carddemo-3270.tape` — CardDemo driven through c3270 against
    `forge-run`, recorded with vhs;
  - `cobble.sh`, `cobble_features.sh`, `srccfg.sh` — cobble evidence.
- `tools/rebuild-all.sh` / `make carddemo-all` — every artifact the pipeline segment shows.
- `docs/how-to/analyse-a-corpus.md` — the stage-by-stage commands.

## Deliverables

1. The narrative and a per-segment script (talking points, on-screen actions, exact commands,
   which artifact page to open). Location and format: see Decisions left open.
2. The agent skill, plus whatever small, tested helpers it needs to read the artifacts.
3. Possibly more later (the user said "there may be more things").

## Constraints

- The user records and edits; the deliverables make that easy (commands copy-pasteable, each
  segment self-contained, its prerequisites stated).
- Explainers are concrete: every one carries a CardDemo example (COBOL, a tree, a graph, a row).
- Data security: CardDemo identifiers only.

## How Q1 and Q2 were answered (the method the skill encodes)

The figures above are from a dry run on `cobble/out-carddemo-20261028-0447-rebuild-all`; they are
estimates, not targets.

- **Q1.** `bms/metadata.json` maps the label "Current Balance" to field `ACURBAL` on map
  `CACTVWA`. `cobble-trace-query backward COACTVWC.ACURBALO --links combine/links.jsonl` gives
  `ACCT-CURR-BAL`, read from the account file. In `graph.jsonl` the dataset node
  `ACCTDATA.VSAM.KSDS[12:24]` holds those bytes; the fields writing into it are the writers.
- **Q2.** Start from the file slots holding a card number (card file, xref file and its
  alternate-index path, transaction file, daily-transaction file). Walk `graph.jsonl` byte by
  byte, following each edge's alignment: first forward to every copy (passing through larger
  buffers), then backward from each copy to its feeders (never entering a field larger than the
  value). Skip `rebuilt` edges. Treat a field and the field it directly `REDEFINES` (from
  `extents.jsonl`) as one location. Add any file slot reached as a new start, until nothing new
  appears. Check surprising hops against `combine/links.jsonl` (bytes in versus bytes out of a
  commarea), the fixpoint's writer rows (`cobble-dataflow-fixpoint-query writers`) and the
  knowledge graph (`DEFINE PATH` ties an alternate index to its base file).

## Calls made in the design (not the user's)

- Segment 2 shows every stage `tools/rebuild-all.sh` runs, in its order; minor stages (CSD
  synthesis, field accesses, file-site census, class share) get a line each. BMS maps are shown
  because Q1 uses them. The per-program CFG loop is shown on one program.
- The skill and every slide reference one frozen artifact run, rebuilt after the last cobble change
  before recording; the run directory is named in the script. It is not committed.
- The skill is a Claude Code skill in this repo, tracked under `cobble/skills/` and copied into
  `.claude/skills/` by `make skills` (the user's call: `.claude/` stays untracked). Its helpers are workspace code under the repo's
  gates (types, lint, tests).

## The skill (decided by the user)

A generic skill: it answers any question about a corpus from its artifacts, not just Q1 and Q2.
It reasons live, so takes differ; the video records it answering, not a fixed transcript. Q1 and
Q2 are the on-camera examples, and the method above is guidance the skill carries, not a
hard-coded procedure. The skill knows every artifact the pipeline writes, what each answers, and
the query tools that read them, and says where an answer needed judgement.

## Decisions left open

- Final length; an hour is a working guess.
- Where the script lives and its format.

## Left to the builder

- How each explainer is visualised (slides, the existing renders, diagrams).
- The exact talking points' wording.
- Which helper scripts the skill needs, provided they read only artifacts.
