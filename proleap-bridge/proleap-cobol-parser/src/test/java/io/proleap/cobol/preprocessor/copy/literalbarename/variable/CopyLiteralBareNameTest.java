package io.proleap.cobol.preprocessor.copy.literalbarename.variable;

import static org.junit.Assert.assertTrue;

import java.io.File;
import java.util.Arrays;
import java.util.List;

import org.junit.Test;

import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import io.proleap.cobol.preprocessor.impl.CobolPreprocessorImpl;

/**
 * Regression test for red-dragon-pgkk: a quoted-literal {@code COPY 'NAME'}
 * (bare name, no extension) must resolve {@code NAME.cpy} in the copybook
 * directory, mirroring the behaviour of the unquoted {@code COPY NAME} word
 * finder. The literal finder previously matched the candidate's full path
 * including the {@code .cpy} extension, so a bare quoted name never resolved a
 * real {@code .cpy} file.
 */
public class CopyLiteralBareNameTest {

	private static final String DIR = "src/test/resources/io/proleap/cobol/preprocessor/copy/literalbarename/variable";

	@Test
	public void testQuotedBareNameResolvesCpyExtensionViaDirectories() throws Exception {
		final File copyBookDirectory = new File(DIR + "/copybooks");
		final List<File> copyBookDirectories = Arrays.asList(copyBookDirectory);

		final CobolParserParams params = new CobolParserParamsImpl();
		params.setCopyBookDirectories(copyBookDirectories);
		// Mirror the bridge's Main.java configuration: extensions are set, so the
		// absolute matching branch in the literal finder is exercised.
		params.setCopyBookExtensions(Arrays.asList("", "cpy", "CPY", "cob", "cbl", "copy", "COPY"));
		params.setFormat(CobolSourceFormatEnum.VARIABLE);

		final File inputFile = new File(DIR + "/CopyLiteralBareName.cbl");
		final String preProcessedInput = new CobolPreprocessorImpl().process(inputFile, params);

		assertTrue(
				"COPY 'CSSTRPFY' should resolve CSSTRPFY.cpy and inline its content, but got:\n" + preProcessedInput,
				preProcessedInput.contains("Hello Literal Bare"));
	}
}
