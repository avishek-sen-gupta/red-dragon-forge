/**
 * @name Sinks
 * @description Each node's bytes sent out of the program, with the nodes whose writes
 *              they carry: the node itself where it writes them, as a WRITE FROM does,
 *              else what reaches it. By cobble's node ids, for comparison with cobble's
 *              fixpoint.
 * @kind table
 * @id cobol/sinks
 */

import cobol.Definers

private predicate selfWritten(GraphNode g, Atom a) {
  exists(Field w | graphWrites(g, w, false) and fieldAtom(w, a))
}

from GraphNode at, Stmt s, string kind, Field f, Atom a, string definer
where
  s = at.getStmt() and
  sink(s, kind, f) and
  fieldAtom(f, a) and
  (
    selfWritten(at, a) and definer = at.getId()
    or
    not selfWritten(at, a) and
    exists(GraphNode writer | definer(at, a, writer) and definer = writer.getId())
  )
select f.getProgram().getName(), at.getId(), kind, f.getName(), f.getRecord(), f.getStart(),
  f.getLength(), definer
