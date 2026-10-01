# Algorithm explainers — Design

**Date:** 2026-10-01
**Status:** proposed

## Goal

A small set of instructive pages that explain the techniques cobble's field
dataflow is built on, to a **general software engineer** who has never met them:
fixpoint iteration, gen/kill and reaching definitions, byte-extent aliasing, and
value sets for resolving dynamic calls. Each page should leave that reader able to
explain the technique in their own words, predict its answer on a small example,
and say what makes it go wrong or get expensive.

The pages teach the techniques, not the repo. They use small COBOL examples
because that is the domain, and close with a short pointer to where cobble does
the same thing.

## Non-goals

- Documenting cobble's code or CLI for contributors. The README does that.
- Covering every technique in the repo. These four are the first batch; more pages
  follow the same pattern later, each as its own small change.
- Publishing anywhere. The pages live in the repo and open from disk.

## Where and what

```
docs/explainers/
  index.html                  the four topics, one paragraph each, in reading order
  fixpoints.html
  reaching-definitions.html
  byte-extents.html
  value-sets.html
  explainer.css               shared styling
  stepper.js                  shared step-through widget
```

- **Static, self-contained, no build step.** Each page opens directly from disk.
  No server, no bundler, no framework, and no network: no CDN scripts or fonts.
- **Classic scripts, not ES modules.** Browsers refuse module imports from
  `file://`, so `stepper.js` and each page's model are plain `<script>` files.
- **One look.** `explainer.css` reuses `docs/presentation/theme.css`'s palette
  (ink ground, phosphor and amber accents) so the docs read as one family. It
  defines both a dark and a light scheme through `prefers-color-scheme`, and lays
  out at phone width without horizontal scrolling.

## Page anatomy

Every page has the same seven sections, in this order:

1. **The problem.** One paragraph, framed for an engineer who has never seen it.
2. **The intuition.** The idea in plain words, before any notation.
3. **The example.** One COBOL program, 10–20 lines — the smallest that shows the
   point.
4. **Step through it.** The page's model running on that example, one step at a
   time, through the shared widget: back, next, play, reset. Each step shows what
   changed and why, in one sentence.
5. **The rule.** The technique stated precisely: the equations or the invariant.
6. **What goes wrong.** The surprising or costly cases, and how they show up.
7. **In cobble.** Two or three sentences and links to the source files that do this
   for real.

## The four pages

### Fixpoints and worklists (`fixpoints.html`)

- **Point:** a dataflow analysis is "keep applying the rules until nothing
  changes"; the answer is unique because the facts only grow; the visiting order
  changes how long it takes, not what it finds.
- **Example:** a `PERFORM … UNTIL` loop whose body writes `WS-B` from `WS-A`, and a
  read of `WS-B` after the loop that writes `WS-C`.
- **Step-through:** the control-flow graph, each node's state, and the worklist.
  The reader can switch between first-in-first-out and reverse-postorder order and
  watch both reach the same final state in different numbers of steps.
- **Answer checked:** the field flows (source field → target field).
- **What goes wrong:** order and visit counts (cobble's largest program went from
  about 107,000 visits to about 20,000 by changing order alone); budgets, and what
  stopping early means — a subset of the flows, never a wrong one.

### Gen/kill and reaching definitions (`reaching-definitions.html`)

- **Point:** for each read, which writes could have produced the value it sees.
- **Example:** an `IF … ELSE` that assigns `WS-A` in both arms, a read of `WS-A` after
  the `IF`, then an unconditional `MOVE` to `WS-A` and a second read.
- **Step-through:** per statement, the set of definitions that reach it; gen adds a
  write, kill removes the writes it replaces, a merge takes the union.
- **Answer checked:** the reaching definitions per read: the first read has both
  arms' writes as definers, the second has only the unconditional one.
- **What goes wrong:** strong versus weak updates — a write may only kill what it is
  certain to overwrite — and loops, which bring a definition back around.

### Byte-extent aliasing (`byte-extents.html`)

- **Point:** in COBOL, memory is bytes, not variables. A field is a byte range, two
  fields alias when their ranges overlap, and group moves, `REDEFINES` and partial
  overlaps all follow from that one idea.
- **Example:** a group `REC` with children `WS-A` (bytes 0–4) and `WS-B` (bytes
  4–8), a `REDEFINES` over part of it, and moves into the group, into one child,
  and out of the redefinition.
- **Step-through:** a byte strip of the record, coloured by which write last
  touched each byte, showing which reads see which writes.
- **Answer checked:** the flows and reaching definitions: a group write reaches a
  child read, and a write to one child does not kill the group's other bytes.
- **What goes wrong:** must-cover versus may-alias. Only a write that fully covers
  a range can kill the definitions of that range; anything less leaves them alive.

### Value sets and dynamic calls (`value-sets.html`)

- **Point:** `CALL WS-PGM` names a program only at run time; tracking the set of
  byte values a field can hold resolves it statically, along with the reason when
  the set may be incomplete.
- **Example:** two branches moving different literals into `WS-PGM` before a
  `CALL WS-PGM`, and a second call through a field nothing assigns.
- **Step-through:** the value set of `WS-PGM` at each statement, its join at the
  merge, and the call site's resolution.
- **Answer checked:** the call targets: the first site's candidates are both
  literals; the second has no candidates and the reason `uninitialised`.
- **What goes wrong:** under-approximation and its reasons (`uninitialised`,
  `over-budget`, `incomplete-walk`), and the proven / candidate / unresolved rule
  that decides what a downstream graph may claim.

## One source of truth per example

Each page embeds one block:

```html
<script type="application/json" id="example">
  {"program": "<COBOL source>", "expected": { … }}
</script>
```

- `program` is the COBOL the page shows and the program the checks analyse, so the
  displayed code and the checked code cannot drift apart.
- `expected` is the page's final answer, in the shape that page checks: flows as
  `(source, target)` field pairs, reaching definitions as definers per read, or
  call targets as candidates and reasons per site.

## Checks

**cobble agrees with every page's answer — enforced by the test suite.**
`cobble/tests/explainers/test_explainers.py` does this for each page:

1. Extract the embedded block, and validate it into a typed model.
2. Parse `program` with the ProLeap bridge, exactly as `test_fields_synthetic.py`
   parses its programs.
3. Run cobble's field dataflow on the result.
4. Assert that cobble's answer, in the page's shape, equals `expected`.

It follows `test_fields_synthetic.py`'s handling of the bridge JAR, so it runs
wherever that file does.

**The page's model agrees with its answer — checked in the page.** On load, each
page runs its model to the end and compares the final state with `expected`. On a
mismatch it shows a red banner naming the difference. This is not part of the
commit gate: Node is not in the repo's toolchain, and this design does not add it.

## Content rules

- **Invented examples only.** Field and program names are generic (`WS-A`, `REC`,
  `PROGB`). Nothing is taken from any corpus under analysis. This follows the
  data-security rules.
- **Dense and precise.** Short sentences; no claim the page cannot show. No test
  counts or timings that would go stale, except the one measured order effect,
  which is stated as a historical fact with its context.
- **No comments in the JavaScript** beyond a one-line header per file. The model
  code should read as an explanation in its own right.

## Testing

- **`test_explainers.py`:** one test per page, as described above.
- **A mutation check per page:** change one value in the page's `expected` block
  and confirm its test fails; then restore it.
- **By hand, once per page:** open the page from disk; step forward and back
  through the whole example; confirm no red banner appears; check both colour
  schemes and a phone-width window.

## Out of scope for this batch

- Topics beyond the four, such as control-flow graphs from `PERFORM` and `GO TO`,
  commarea aliasing across programs, and backward tracing. Each can be its own page
  later.
- Running the JavaScript models in CI.
- Linking these pages from the presentation deck.
