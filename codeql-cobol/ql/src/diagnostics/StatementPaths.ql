/**
 * @name Statement node ids
 * @description Every statement with cobble's node id for it and its kind, for comparison
 *              with cobble's fixpoint.
 * @kind table
 * @id cobol/statement-paths
 */

import cobol.Ast

from Stmt s
select unitOf(s).getProgram().getName(), stmtPath(s), s.getAPrimaryQlClass()
