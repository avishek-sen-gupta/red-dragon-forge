/*
 * Copyright (C) 2017, Ulrich Wolffgang <ulrich.wolffgang@proleap.io>
 * All rights reserved.
 *
 * This software may be modified and distributed under the terms
 * of the MIT license. See the LICENSE file for details.
 */

package io.proleap.cobol.preprocessor.sub.copybook.impl;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import io.proleap.cobol.CobolPreprocessorParser.LiteralContext;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.asg.util.FilenameUtils;
import io.proleap.cobol.preprocessor.sub.copybook.LiteralCopyBookFinder;
import io.proleap.cobol.preprocessor.sub.util.PreprocessorStringUtils;

public class LiteralCopyBookFinderImpl implements LiteralCopyBookFinder {

	private final static Logger LOG = LoggerFactory.getLogger(LiteralCopyBookFinderImpl.class);

	@Override
	public File findCopyBook(final CobolParserParams params, final LiteralContext ctx) {
		if (params.getCopyBookFiles() != null) {
			for (final File copyBookFile : params.getCopyBookFiles()) {
				if (isMatchingCopyBook(copyBookFile, null, ctx)) {
					return copyBookFile;
				}
			}
		}

		if (params.getCopyBookDirectories() != null) {
			for (final File copyBookDirectory : params.getCopyBookDirectories()) {
				final File validCopyBook = findCopyBookInDirectory(copyBookDirectory, ctx);

				if (validCopyBook != null) {
					return validCopyBook;
				}
			}
		}

		return null;
	}

	protected File findCopyBookInDirectory(final File copyBooksDirectory, final LiteralContext ctx) {
		try {
			for (final File copyBookCandidate : Files.walk(copyBooksDirectory.toPath()).map(Path::toFile)
					.collect(Collectors.toList())) {
				if (isMatchingCopyBook(copyBookCandidate, copyBooksDirectory, ctx)) {
					return copyBookCandidate;
				}
			}
		} catch (final IOException e) {
			LOG.warn(e.getMessage(), e);
		}

		return null;
	}

	protected boolean isMatchingCopyBook(final File copyBookCandidate, final File cobolCopyDir,
			final LiteralContext ctx) {
		final String copyBookIdentifier = PreprocessorStringUtils.trimQuotes(ctx.getText()).replace("\\", "/");
		final boolean result;

		if (cobolCopyDir == null) {
			result = isMatchingCopyBookRelative(copyBookCandidate, copyBookIdentifier);
		} else {
			result = isMatchingCopyBookAbsolute(copyBookCandidate, cobolCopyDir, copyBookIdentifier);
		}

		return result;
	}

	protected boolean isMatchingCopyBookAbsolute(final File copyBookCandidate, final File cobolCopyDir,
			final String copyBookIdentifier) {
		final Path copyBookCandidateAbsolutePath = Paths.get(copyBookCandidate.getAbsolutePath()).normalize();
		final Path copyBookIdentifierAbsolutePath = Paths.get(cobolCopyDir.getAbsolutePath(), copyBookIdentifier)
				.normalize();

		// Exact, extension-sensitive match: covers COPY 'NAME.cpy' and
		// path-qualified forms where the identifier already carries the extension.
		if (copyBookIdentifierAbsolutePath.toString().equalsIgnoreCase(copyBookCandidateAbsolutePath.toString())) {
			return true;
		}

		// Extension-tolerant match mirroring CobolWordCopyBookFinderImpl: a bare
		// quoted name such as COPY 'NAME' must resolve NAME.cpy. Strip the
		// extension from the candidate file name and compare it against the final
		// segment of the identifier, while still requiring the directory portion of
		// the resolved identifier path to match the candidate's directory.
		return isMatchingByBaseName(copyBookCandidateAbsolutePath, copyBookIdentifierAbsolutePath);
	}

	/**
	 * Returns true when the candidate's directory equals the identifier's
	 * directory (case-insensitively) and the candidate's base name (extension
	 * stripped) equals the identifier's final segment (extension stripped). This
	 * lets a bare quoted COPY name match a real copybook file regardless of its
	 * extension, without matching files whose base name merely contains the
	 * identifier as a substring.
	 */
	protected boolean isMatchingByBaseName(final Path copyBookCandidateAbsolutePath,
			final Path copyBookIdentifierAbsolutePath) {
		final Path candidateParent = copyBookCandidateAbsolutePath.getParent();
		final Path identifierParent = copyBookIdentifierAbsolutePath.getParent();

		if (candidateParent == null || identifierParent == null) {
			return false;
		}

		if (!candidateParent.toString().equalsIgnoreCase(identifierParent.toString())) {
			return false;
		}

		final String candidateBaseName = FilenameUtils.getBaseName(copyBookCandidateAbsolutePath.getFileName().toString());
		final String identifierBaseName = FilenameUtils
				.getBaseName(copyBookIdentifierAbsolutePath.getFileName().toString());
		return candidateBaseName.equalsIgnoreCase(identifierBaseName);
	}

	protected boolean isMatchingCopyBookRelative(final File copyBookCandidate, final String copyBookIdentifier) {
		final Path copyBookCandidateAbsolutePath = Paths.get(copyBookCandidate.getAbsolutePath()).normalize();
		final Path copyBookIdentifierRelativePath;

		if (copyBookIdentifier.startsWith("/") || copyBookIdentifier.startsWith("./")
				|| copyBookIdentifier.startsWith("\\") || copyBookIdentifier.startsWith(".\\")) {
			copyBookIdentifierRelativePath = Paths.get(copyBookIdentifier).normalize();
		} else {
			copyBookIdentifierRelativePath = Paths.get("/" + copyBookIdentifier).normalize();
		}

		// Exact, extension-sensitive suffix match: covers COPY 'NAME.cpy' and
		// path-qualified forms where the identifier already carries the extension.
		if (copyBookCandidateAbsolutePath.toString().toLowerCase()
				.endsWith(copyBookIdentifierRelativePath.toString().toLowerCase())) {
			return true;
		}

		// Extension-tolerant match mirroring CobolWordCopyBookFinderImpl: strip the
		// extension from the candidate file name and from the identifier's final
		// segment, then require the candidate path to end with the identifier
		// directory portion + matching base name. This lets COPY 'NAME' resolve
		// NAME.cpy without matching files that merely contain NAME as a substring.
		final Path identifierParent = copyBookIdentifierRelativePath.getParent();
		final String candidateBaseName = FilenameUtils
				.getBaseName(copyBookCandidateAbsolutePath.getFileName().toString());
		final String identifierBaseName = FilenameUtils
				.getBaseName(copyBookIdentifierRelativePath.getFileName().toString());

		if (!candidateBaseName.equalsIgnoreCase(identifierBaseName)) {
			return false;
		}

		final Path candidateParent = copyBookCandidateAbsolutePath.getParent();
		if (identifierParent == null || candidateParent == null) {
			// Bare identifier with no directory part: base-name equality suffices,
			// mirroring the word finder which matches any same-name file in the dir.
			return identifierParent == null;
		}

		return candidateParent.toString().toLowerCase().endsWith(identifierParent.toString().toLowerCase());
	}
}
