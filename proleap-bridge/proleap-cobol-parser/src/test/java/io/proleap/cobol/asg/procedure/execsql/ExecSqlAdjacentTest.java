package io.proleap.cobol.asg.procedure.execsql;

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
import io.proleap.cobol.asg.metamodel.procedure.execsql.ExecSqlStatement;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

/**
 * Adjacent EXEC SQL statements with NO intervening period (legal COBOL inside a
 * PERFORM/IF) must each become a SEPARATE ExecSqlStatement. ProLeap historically
 * merged a run of consecutive *>EXECSQL marker lines via {@code EXECSQLLINE+},
 * ignoring the per-statement '}' (EXEC_END_TAG) boundary, so the 2nd and 3rd
 * statements were swallowed into the first. This mirrors the EXEC CICS fix
 * (EXECSQLLINE* EXECSQLENDLINE).
 */
public class ExecSqlAdjacentTest extends CobolTestBase {

	@Test
	public void test() throws Exception {
		final File inputFile = new File(
				"src/test/resources/io/proleap/cobol/asg/procedure/execsql/ExecSqlAdjacent.cbl");
		final Program program = new CobolParserRunnerImpl().analyzeFile(inputFile, CobolSourceFormatEnum.TANDEM);

		final CompilationUnit compilationUnit = program.getCompilationUnit("ExecSqlAdjacent");
		final ProgramUnit programUnit = compilationUnit.getProgramUnit();
		final ProcedureDivision procedureDivision = programUnit.getProcedureDivision();

		assertEquals(3, procedureDivision.getStatements().size());

		final String[] expected = {
				"EXEC SQL SELECT A INTO :X FROM T END-EXEC",
				"EXEC SQL UPDATE T SET A = 1 END-EXEC",
				"EXEC SQL DELETE FROM T END-EXEC",
		};
		for (int i = 0; i < expected.length; i++) {
			final ExecSqlStatement stmt = (ExecSqlStatement) procedureDivision.getStatements().get(i);
			assertNotNull(stmt);
			assertEquals(StatementTypeEnum.EXEC_SQL, stmt.getStatementType());
			assertEquals(expected[i], stmt.getExecSqlText());
		}
	}
}
