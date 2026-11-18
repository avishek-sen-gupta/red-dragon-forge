import cobol.ast.internal.Generated

from
  Generated::CobolParagraph p, int i, Generated::MoveStatement m, Generated::RefModOperand s,
  Generated::RefModOperand t
where m = p.getStatements(i) and s = m.getSource() and t = m.getTargets(0)
select p.getName(), i, s.getName(), s.getKind(), t.getName(), m.getSpan().getStartLine()
