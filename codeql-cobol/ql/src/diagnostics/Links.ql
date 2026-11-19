/**
 * @name Links
 * @description Every link between programs once their jumps are answered across programs,
 *              as cobble's combine finds them, by cobble's node ids: the jump, the program
 *              it enters, the caller's bytes and the callee's they are, whether control
 *              comes back, and whether only linking found the callee.
 * @kind table
 * @id cobol/links
 */

import cobol.Combine

from
  GraphNode n, string kind, boolean returns, Program callee, string crec, int clo, int chi,
  string erec, int elo, int ehi, string discovered
where
  jump(n.getStmt(), kind, returns) and
  (
    entering(n, callee, _, crec, clo, chi, erec, elo, ehi)
    or
    exists(GraphNode r | starting(n, r, crec, clo, chi, erec, elo, ehi) and callee = r.getProgram())
  ) and
  if discovered(n, callee) then discovered = "true" else discovered = "false"
select n.getProgram().getName(), n.getId(), kind, callee.getName(),
  crec + "|" + clo + "|" + (chi - clo), erec + "|" + elo + "|" + (ehi - elo), returns, discovered
