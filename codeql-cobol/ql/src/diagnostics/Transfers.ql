/**
 * @name Field-to-field transfers
 * @description Each statement's moves from one field to another, named by cobble's node
 *              ids, for comparison with cobble's fixpoint.
 * @kind table
 * @id cobol/transfers
 */

import cobol.Ast

from Stmt s, string site, Field src, Field dst
where transfer(s, src, dst) and site = "" or loopTransfer(s, site, src, dst)
select src.getProgram().getName(), stmtPath(s) + site, src.getName(), src.getRecord(),
  src.getStart(), src.getLength(), dst.getName(), dst.getRecord(), dst.getStart(),
  dst.getLength()
