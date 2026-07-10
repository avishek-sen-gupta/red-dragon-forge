package io.proleap.cobol.asg.procedure.evaluate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.File;

import org.junit.Test;

import io.proleap.cobol.CobolTestBase;
import io.proleap.cobol.asg.metamodel.CompilationUnit;
import io.proleap.cobol.asg.metamodel.Literal;
import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.ProgramUnit;
import io.proleap.cobol.asg.metamodel.procedure.ProcedureDivision;
import io.proleap.cobol.asg.metamodel.procedure.StatementTypeEnum;
import io.proleap.cobol.asg.metamodel.procedure.evaluate.Condition;
import io.proleap.cobol.asg.metamodel.procedure.evaluate.EvaluateStatement;
import io.proleap.cobol.asg.metamodel.procedure.evaluate.Value;
import io.proleap.cobol.asg.metamodel.procedure.evaluate.When;
import io.proleap.cobol.asg.metamodel.procedure.evaluate.WhenPhrase;
import io.proleap.cobol.asg.metamodel.valuestmt.LiteralValueStmt;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

public class EvaluateStatementDfhRespTest extends CobolTestBase {

	@Test
	public void test() throws Exception {
		final File inputFile = new File(
				"src/test/resources/io/proleap/cobol/asg/procedure/evaluate/DfhRespEvaluate.cbl");
		final Program program = new CobolParserRunnerImpl().analyzeFile(inputFile, CobolSourceFormatEnum.TANDEM);

		final CompilationUnit compilationUnit = program.getCompilationUnit("DfhRespEvaluate");
		final ProgramUnit programUnit = compilationUnit.getProgramUnit();
		final ProcedureDivision procedureDivision = programUnit.getProcedureDivision();
		assertEquals(1, procedureDivision.getStatements().size());

		final EvaluateStatement evaluateStatement =
				(EvaluateStatement) procedureDivision.getStatements().get(0);
		assertNotNull(evaluateStatement);
		assertEquals(StatementTypeEnum.EVALUATE, evaluateStatement.getStatementType());
		assertNotNull(evaluateStatement.getSelect());
		assertEquals(2, evaluateStatement.getWhenPhrases().size());
		assertNotNull(evaluateStatement.getWhenOther());

		for (final WhenPhrase whenPhrase : evaluateStatement.getWhenPhrases()) {
			assertEquals(1, whenPhrase.getWhens().size());

			final When when = whenPhrase.getWhens().get(0);
			final Condition condition = when.getCondition();
			assertNotNull(condition);
			assertEquals(Condition.ConditionType.VALUE, condition.getConditionType());

			final Value value = condition.getValue();
			assertNotNull(value);
			assertTrue("DFHRESP(x) must be parsed as a LiteralValueStmt, not an identifier",
					value.getValueStmt() instanceof LiteralValueStmt);

			final LiteralValueStmt literalValueStmt = (LiteralValueStmt) value.getValueStmt();
			assertEquals(Literal.LiteralType.CICS_DFH_RESP, literalValueStmt.getLiteral().getLiteralType());

			assertEquals(1, whenPhrase.getStatements().size());
		}
	}
}
