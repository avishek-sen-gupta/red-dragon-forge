# Design: execution-order simulator for cobble CFGs

## Problem

Questions of the shape "list every paragraph that executes, in order, until
control returns to the caller" need a walk over the CFG `cobble-srccfg-build`
writes that respects COBOL's actual call-stack semantics. Two tool classes
exist today, and neither does this directly:

1. **Plain graph BFS/DFS over the exported CFG JSON.** Flow-INSENSITIVE: a
   paragraph's `#end` node carries both a `RETURN` edge (to whichever
   `PERFORM...THRU` call closes there) and a `FALLTHRU` edge (what would
   happen if reached by straight-line fall-through instead), and which one
   is correct depends on which `PERFORM` frame is currently active --
   information no single edge carries. Measured failure modes on a real
   question, tracing a `PERFORM TARGET-PARA THRU TARGET-EXIT` call on a real
   production COBOL program (~1250 CFG nodes):
   - Following every `FALLTHRU`: explodes to ~85% of the whole program's
     nodes -- continues straight through the real `RETURN` into the caller
     and keeps going into the caller's own subsequent, unrelated code.
   - Excluding all `FALLTHRU`: stops after a handful of nodes -- prunes
     legitimate same-closure sequencing (the target paragraph's own body
     falls through to the next paragraph in its `THRU` range because it's
     still inside the *outer* `PERFORM...THRU` boundary, not yet at that
     range's own end label).
   - A corrected version (track a stack of pending `THRU`-range end labels,
     only take `RETURN` when standing exactly on the top-of-stack's end
     label) gets the shape right but still had a real bug: the
     "have we returned to the caller" check looked for the caller
     paragraph's `#label` entry node, but a `RETURN` edge's target is
     wherever the original `PERFORM` statement sits -- typically a
     mid-paragraph node (e.g. `CALLER/4#test`), never the `#label`. The
     check never fired; the walk ran straight past the real stop point into
     the caller's own subsequent, unrelated paragraphs.

2. **`cobble-fields-trace --record-paths`.** This already has a correct,
   carefully-designed stack/`RETURN`/dead-end walker (`Frame`, `_sequel`,
   `_admissible`, `_return_edge`, `_open`/`_marked` in
   `cobble/dataflow/fields/trace.py`) -- confirmed by reading the actual
   code, not assumed. But it is built for a different question: **byte
   provenance and branch coverage**, sampled from the program's own real
   entry point, with a plan mechanism that deliberately explores different
   branch choices across samples to maximize *new* coverage per path. Two
   consequences that make it the wrong tool for "list execution order from
   this specific call site":
   - It starts from the program's entry point, not an arbitrary `PERFORM`
     site. The pure base route (`path_index=0`, "every decision takes its
     first arm" -- confirmed from the `_Queue` docstring, "it starts
     holding the empty plan") was a small fraction of the program's size on
     this real member and never reached the target call at all; reaching
     any specific deep nested call requires deliberately flipped branch
     choices, which is the tool doing its job (coverage), not a bug -- but
     it means there is no way to ask it to start exactly where we want
     without walking (or re-deriving) its sampling order.
   - The `_open`/`_marked` re-entry rule (`_max_visits`: one visit per node,
     two for a `#loop` header, before an edge back into an open frame is
     refused) can substitute a different edge than the literal source
     statement when a paragraph's frame is still open and gets re-entered
     -- observed on this real program: one error-handler paragraph does a
     literal `GO TO` back into the shared screen-send paragraph whose own
     raise reached that handler in the first place, so the frame is still
     open. A sampled path showed content *after* the screen-send paragraph
     despite that paragraph's own terminal node (`GOBACK`) having zero
     outgoing edges in the raw CFG -- consistent with, but not fully
     confirmed as, the re-entry rule swapping in a fallback edge rather than
     the real `GOTO`. Not chased further; flagged here as the thing to
     verify before trusting a provenance-sampled path as a literal
     single-execution trace near a recursive raise.

## What to reuse, not re-derive

`cobble.dataflow.fields.trace` already has the right primitives. Import and
call them directly rather than re-implementing stack/return logic a second
time (badly, on the first two attempts above):

| Function / type | What it gives us |
|---|---|
| `Frame` | one open `PERFORM`/call invocation: `resume` (where it returns to), `visits` (per-node count for the re-entry rule) |
| `_sequel(cfg, node)` | where a call or PERFORM continues once it returns -- reads `cfg.node(node).resume` first, falls back to the node's own `FLOW` edge |
| `_admissible(walk, loaded, edges)` | the real candidate edges at a node: drops `PERFORM`/`RETURN` edges (handled separately), drops anything the re-entry rule refuses, sorts dead-end arms last |
| `_return_edge(walk, edges)` | the one `RETURN` edge that matches the *current* frame's own resume point -- explicitly rejects a `RETURN` targeting a different, coincidentally-matching frame |
| `_open(stack, program, node)` / `_marked(stack, node)` | the re-entry guard and its bookkeeping |
| `Cfg` (from `cobble.dataflow.srccfg.build.build_program(asg)`) | the real typed CFG object these functions expect -- built from the ASG directly, not from the exported `cobble-srccfg-build` JSON (which is a plain dict dump; `Cfg.node()`/`.successors()` aren't available on it) |

This means the simulator should load the ASG and call `build_program(asg)`
itself (same call the fixpoint and `cobble-srccfg-build` both make), not
start from the already-exported CFG JSON other tools in this family use.

## Proposed shape

A minimal walker, built on top of the imports above, that differs from
`cobble-fields-trace` in exactly the ways this question class needs:

1. **Starts at an arbitrary node** (the `PERFORM` site in question), not the
   program's entry point -- seed a single `Frame` whose `resume` is the
   known stop point (the node right after the `PERFORM` in the caller),
   rather than deriving it by sampling from the top.
2. **No coverage plan, no branch-maximizing exploration.** At a `TEST`
   node, don't pick one arm by a plan -- recurse down *both*, since the
   question wants every paragraph that *could* execute, not one sampled
   scenario. This is the one deliberate deviation from `cobble-fields-trace`'s
   own semantics (which picks one arm per path) -- stated explicitly here so
   it isn't mistaken for parity with it.
3. **Reuses `_sequel`/`_admissible`/`_return_edge`/`_open`/`_marked` verbatim**
   for everything else -- `PERFORM` continuation, dead-end-last ordering,
   stack-correct `RETURN`, and the re-entry cap -- instead of a hand-rolled
   version of any of them.
4. **Stops the moment the walk reaches the seeded `Frame`'s own `resume`
   point with an empty stack** -- the literal "control has returned to the
   caller" condition, checked against the real resume node id, not against
   a `#label`/paragraph-name guess (the bug that broke the second BFS
   attempt).
5. **Reports, rather than silently resolves, every place `_open` refuses a
   re-entry** -- so a recursive-raise case like the one observed above
   shows up in the output as "blocked by the re-entry rule, real COBOL
   would re-run this paragraph" instead of quietly substituting whatever
   edge `_admissible` picks instead.

## Open questions before building this

- Does `_admissible`/`_return_edge` need `Loaded`/`walk.store` populated for
  anything beyond the fields this simulator cares about (control flow only,
  no byte provenance)? If the Store/Dep machinery is entangled with the
  control-flow decision functions rather than cleanly separable, a thin
  wrapper may need to pass dummy/empty values through -- worth checking
  the full call sites of `_admissible`/`_return_edge` before assuming they
  decompose as cleanly as the signatures above suggest.
- Confirm (don't assume) that the re-entry-rule substitution hypothesis
  above is actually what happened in the observed case, by stepping
  `_admissible` by hand against that exact node/stack state, before citing
  it as settled fact in any future answer.
- Decide how to render a two-armed `TEST` tree for a long chain -- a deep
  binary tree needs a different layout than a wide flat fan-out, not yet
  designed.
