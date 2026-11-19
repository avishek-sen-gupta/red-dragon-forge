/**
 * @name Jumps
 * @description Every jump between programs, as cobble's fixpoint reads it, by cobble's
 *              node ids: its kind, whether control comes back, its target and
 *              transaction, the areas it hands over, and what holds each target,
 *              transaction and cell of an area there -- its values, writers and
 *              reasons. A program's entry is a jump of its own, with the areas it is
 *              entered with.
 * @kind table
 * @id cobol/jumps
 */

import cobol.Values

bindingset[f, lo, hi]
private string bytes(Field f, int lo, int hi) { result = f.getRecord() + "|" + lo + "|" + (hi - lo) }

private string whole(Field f) { result = bytes(f, f.getStart(), f.getEnd()) }

private predicate fact(GraphNode n, string part, int param, string area, string extent, string attr, string text) {
  exists(Field a, Field f, int lo, int hi, string rec |
    factExtent(n, part, param, a, f, lo, hi) and
    rec = f.getRecord() and
    (if part = "field" then area = whole(a) else area = "") and
    extent = bytes(f, lo, hi)
  |
    attr = "at" and text = ""
    or
    attr = "value" and value(n, rec, lo, hi, text)
    or
    attr = "reason" and reason(n, rec, lo, hi, text)
    or
    attr = "writer" and exists(GraphNode d | writer(n, rec, lo, hi, d) and text = d.getId())
  )
}

private predicate jumpRow(
  GraphNode n, Stmt s, string part, int param, string area, string extent, string attr,
  string text
) {
  s = n.getStmt() and
  jump(s, _, _) and
  (
    part = "jump" and param = -1 and area = "" and extent = "" and attr = "at" and text = ""
    or
    part = "target" and param = -1 and area = "" and extent = "" and attr = "literal" and jumpTargetName(s, text)
    or
    part = "transid" and param = -1 and area = "" and extent = "" and attr = "literal" and jumpTransidText(s, text)
    or
    part = "area" and
    extent = "" and
    attr = "at" and
    text = "" and
    exists(Field a | area = whole(a) |
      jumpArea(s, param, a) or jump(s, "EXIT", _) and received_area(n.getProgram(), param, a)
    )
    or
    fact(n, part, param, area, extent, attr, text)
  )
}

from
  string program, string node, int line, string kind, string returns, string part, int param,
  string area, string extent, string attr, string text
where
  exists(GraphNode n, Stmt s, boolean r |
    jumpRow(n, s, part, param, area, extent, attr, text) and
    jump(s, kind, r) and
    program = n.getProgram().getName() and
    node = n.getId() and
    line = n.getLocation().getStartLine() and
    returns = r.toString()
  )
  or
  exists(Program p |
    program = p.getName() and
    node = "" and
    line = 0 and
    kind = "ENTRY" and
    returns = "false" and
    extent = "" and
    attr = "at" and
    text = ""
  |
    part = "jump" and param = -1 and area = ""
    or
    part = "area" and exists(Field a | received_area(p, param, a) and area = whole(a))
  )
select program, node, line, kind, returns, part, param, area, extent, attr, text
