/**
 * @name Graph edges
 * @description Every edge of cobble's graph, with its kind.
 * @kind table
 * @id cobol/demo/cfg-edges
 */

import cobol.Cfg

from GraphNode a, GraphNode b, string kind
where b = a.getASuccessor(kind)
select a.getProgram().getName(), a.getId(), b.getId(), kind
