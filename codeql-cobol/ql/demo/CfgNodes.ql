/**
 * @name Graph nodes
 * @description Every node of cobble's graph, with the kind it is drawn as and its label.
 * @kind table
 * @id cobol/demo/cfg-nodes
 */

import cobol.Cfg

string drawnKind(GraphNode g) {
  if g.getStmt() instanceof Generated::ReadStatement
  then result = "READ"
  else
    if g.getStmt() instanceof Generated::WriteStatement
    then result = "WRITE"
    else
      if g.getStmt() instanceof Generated::RewriteStatement
      then result = "REWRITE"
      else
        if g.getStmt() instanceof Generated::DisplayStatement
        then result = "DISPLAY"
        else result = g.getKind()
}

string detail(GraphNode g, Stmt s) {
  if exists(s.(Generated::ReadStatement).getFileName())
  then result = " " + s.(Generated::ReadStatement).getFileName()
  else
    if exists(s.(Generated::WriteStatement).getRecordName())
    then result = " " + s.(Generated::WriteStatement).getRecordName()
    else
      if exists(s.(Generated::RewriteStatement).getRecordName())
      then result = " " + s.(Generated::RewriteStatement).getRecordName()
      else
        if exists(g.getASuccessor("PERFORM"))
        then result = " " + min(GraphNode t | t = g.getASuccessor("PERFORM") | t.getId())
        else
          if exists(s.getAWrite())
          then
            result =
              " → " + min(Field f | f = s.getAWrite() | f.getName()) +
                plusMore(count(Field f | f = s.getAWrite()))
          else result = ""
}

bindingset[n]
string plusMore(int n) { if n > 1 then result = " +" + (n - 1) else result = "" }

string label(GraphNode g) {
  exists(Stmt s | s = g.getStmt() |
    result = s.getAPrimaryQlClass().regexpReplaceAll("Statement$", "").toUpperCase() + detail(g, s)
  )
  or
  not exists(g.getStmt()) and result = g.getId()
}

from GraphNode g
select g.getProgram().getName(), g.getId(), drawnKind(g), g.getProgram().getName() + " " + label(g)
