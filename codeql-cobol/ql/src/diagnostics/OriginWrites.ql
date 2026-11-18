/**
 * @name Writes from outside the program's storage
 * @description Each statement's writes from a literal, a file, CICS, a CALL, a map or a
 *              function, named by cobble's node ids, for comparison with cobble's
 *              fixpoint.
 * @kind table
 * @id cobol/origin-writes
 */

import cobol.Ast

from Stmt s, string site, string origin, Field dst
where originWrite(s, origin, dst) and site = "" or loopOriginWrite(s, site, origin, dst)
select dst.getProgram().getName(), stmtPath(s) + site, origin, dst.getName(), dst.getRecord(),
  dst.getStart(), dst.getLength()
