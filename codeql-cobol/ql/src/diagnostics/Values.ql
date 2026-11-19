/**
 * @name Values
 * @description For each piece of a cell a node reads, the values its bytes can hold
 *              there and why the values may be short, by cobble's node ids, for
 *              comparison with cobble's fixpoint.
 * @kind table
 * @id cobol/values
 */

import cobol.Values

from GraphNode n, Field f, int lo, int hi, string kind, string text
where
  piece(n, f, lo, hi) and
  (
    value(n, f.getRecord(), lo, hi, text) and kind = "value"
    or
    reason(n, f.getRecord(), lo, hi, text) and kind = "reason"
  )
select f.getProgram().getName(), n.getId(), f.getName(), f.getRecord(), lo, hi - lo, kind, text
