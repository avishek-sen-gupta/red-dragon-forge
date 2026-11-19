/**
 * @name Targets
 * @description Every site naming the program it goes to, or the CICS file it touches, by
 *              a data item, as cobble's fixpoint resolves it within the program, by
 *              cobble's node ids: the names the item can hold, trimmed, those that cannot
 *              name such a thing, and why the names may be short. A file site also
 *              gives what holds its operand -- its values, writers and reasons.
 * @kind table
 * @id cobol/targets
 */

import cobol.Values

private string part(string kind) {
  kind = "program" and result = "target" or kind = "file" and result = "file"
}

private predicate held(GraphNode n, string kind, string attr, string text) {
  exists(Field f, int lo, int hi | factExtent(n, part(kind), _, _, f, lo, hi) |
    attr = "value" and value(n, f.getRecord(), lo, hi, text)
    or
    attr = "reason" and reason(n, f.getRecord(), lo, hi, text)
    or
    attr = "writer" and exists(GraphNode d | writer(n, f.getRecord(), lo, hi, d) and text = d.getId())
  )
}

from
  GraphNode n, string kind, string transfer, string expression, string attr, string text
where
  dynamicSite(n.getStmt(), kind, transfer, expression) and
  (
    exists(string v, string name |
      held(n, kind, "value", v) and name = v.regexpReplaceAll("\\s+$", "")
    |
      if canName(kind, name) then (attr = "candidate" and text = name) else (attr = "dropped" and text = name)
    )
    or
    attr = "reason" and held(n, kind, "reason", text)
    or
    attr = "reason" and text = "no-extent" and not factExtent(n, part(kind), _, _, _, _, _)
    or
    kind = "file" and
    (
      attr = "operand-value" and held(n, kind, "value", text)
      or
      attr = "operand-writer" and held(n, kind, "writer", text)
      or
      attr = "operand-reason" and held(n, kind, "reason", text)
      or
      attr = "operand-extent" and
      exists(Field f, int lo, int hi | factExtent(n, "file", _, _, f, lo, hi) |
        text = f.getRecord() + "|" + lo + "|" + (hi - lo)
      )
    )
    or
    attr = "site" and text = ""
  )
select n.getProgram().getName(), n.getId(), kind, transfer, expression, attr, text
