package io.proleap.cobol.asg.procedure.execcics;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

import java.io.File;

import org.junit.Test;

import io.proleap.cobol.CobolTestBase;
import io.proleap.cobol.asg.metamodel.CompilationUnit;
import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.ProgramUnit;
import io.proleap.cobol.asg.metamodel.procedure.ProcedureDivision;
import io.proleap.cobol.asg.metamodel.procedure.StatementTypeEnum;
import io.proleap.cobol.asg.metamodel.procedure.execcics.ExecCicsStatement;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

/**
 * Adjacent EXEC CICS statements with NO intervening period (legal COBOL inside a
 * PERFORM/IF) must each become a SEPARATE ExecCicsStatement. ProLeap historically
 * merged a run of consecutive *>EXECCICS marker lines via {@code EXECCICSLINE+},
 * ignoring the per-statement '}' (EXEC_END_TAG) boundary, so the 2nd and 3rd
 * statements were swallowed into the first.
 */
public class ExecCicsAdjacentTest extends CobolTestBase {

	@Test
	public void test() throws Exception {
		final File inputFile = new File(
				"src/test/resources/io/proleap/cobol/asg/procedure/execcics/ExecCicsAdjacent.cbl");
		final Program program = new CobolParserRunnerImpl().analyzeFile(inputFile, CobolSourceFormatEnum.TANDEM);

		final CompilationUnit compilationUnit = program.getCompilationUnit("ExecCicsAdjacent");
		final ProgramUnit programUnit = compilationUnit.getProgramUnit();
		final ProcedureDivision procedureDivision = programUnit.getProcedureDivision();

		assertEquals(3, procedureDivision.getStatements().size());

		final String[] expected = {
				"EXEC CICS SEND MAP('M') MAPSET('S') END-EXEC",
				"EXEC CICS RECEIVE MAP('M') MAPSET('S') END-EXEC",
				"EXEC CICS RETURN END-EXEC",
		};
		for (int i = 0; i < expected.length; i++) {
			final ExecCicsStatement stmt = (ExecCicsStatement) procedureDivision.getStatements().get(i);
			assertNotNull(stmt);
			assertEquals(StatementTypeEnum.EXEC_CICS, stmt.getStatementType());
			assertEquals(expected[i], stmt.getExecCicsText());
		}
	}
}
