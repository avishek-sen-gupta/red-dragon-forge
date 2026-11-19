/**
 * @name Linked targets
 * @description Every site naming its program or file by a data item, as cobble's combine
 *              answers it once programs are linked, by cobble's node ids: the names its
 *              operand can hold, trimmed, those that cannot name such a thing, and why the
 *              names may be short.
 * @kind table
 * @id cobol/linked-targets
 */

import cobol.Combine

private string part(string kind) {
  kind = "program" and result = "target"
  or
  kind = "file" and result = "file"
}

from GraphNode n, string kind, string transfer, string expression, string attr, string text
where
  dynamicSite(n.getStmt(), kind, transfer, expression) and
  (
    exists(string v, string name |
      answerValue(n, part(kind), v) and name = v.regexpReplaceAll("\\s+$", "")
    |
      if canName(kind, name)
      then (
        attr = "candidate" and text = name
      ) else (
        attr = "dropped" and text = name
      )
    )
    or
    attr = "reason" and answerReason(n, part(kind), text)
    or
    attr = "site" and text = ""
  )
select n.getProgram().getName(), n.getId(), kind, transfer, expression, attr, text
