/**
 * @name Reaching definitions
 * @description For each node's copy from a cell or consultation of one, the nodes whose
 *              writes it can see, by cobble's node ids, for comparison with cobble's
 *              fixpoint. A write reaches a read along SSA and through PERFORMs, never
 *              into another node's write: what a MOVE copies is a new definition.
 * @kind table
 * @id cobol/reaching-definitions
 */

import cobol.Definers

from GraphNode at, Atom a, GraphNode writer, Field f, string kind
where
  definer(at, a, writer) and
  fieldAtom(f, a) and
  (
    graphCopies(at, f) and kind = "copied"
    or
    cfg_consults(at, f) and kind = "consulted"
  )
select f.getProgram().getName(), at.getId(), kind, f.getName(), f.getRecord(), f.getStart(),
  f.getLength(), writer.getId()
