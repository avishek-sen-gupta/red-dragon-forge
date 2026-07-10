# PROVENANCE

## mapa JCL Grammar

**Source repository:** https://github.com/cschneid-the-elder/mapa

**Commit SHA copied from (HEAD at vendor time):** `2ad7cd5e9c5244499cea07925763ff8c36ab2408`

**Files vendored:**

| Source path in mapa repo             | Destination in jcl-bridge                                         |
|--------------------------------------|-------------------------------------------------------------------|
| `jcl/src/JCLLexer.g4`               | `src/main/antlr4/org/jackal/jcl/JCLLexer.g4`                    |
| `jcl/src/JCLParser.g4`              | `src/main/antlr4/org/jackal/jcl/JCLParser.g4`                   |
| `LICENSE`                            | `LICENSE`                                                         |

**Local edits:** none. Files were copied verbatim; no modifications were made.

**Package / header notes:** Neither grammar file contains an `@header { package ... }` declaration.
The ANTLR Maven plugin generates sources into the `org.jackal.jcl` package as determined by the
grammar file's directory path (`src/main/antlr4/org/jackal/jcl/`). The `JclSerializer.java` uses
`package org.jackal.jcl;` to match.

**Grammar import check:** Neither `JCLLexer.g4` nor `JCLParser.g4` imports additional grammar files.
`JCLParser.g4` uses `options { tokenVocab=JCLLexer; }` which references only the co-vendored lexer.
No additional `.g4` files are required.

**Note on antlr4-tools / Python runtime:** The mapa lexer grammar contains Java-specific embedded
actions (`_modeStack`, `inExecPgmMode`, `myMode`) that the Python ANTLR runtime does not execute.
The Python-runtime parse tree therefore does not correctly model how the Java runtime tokenises JCL.
Rule names used in `JclSerializer.java` were determined by reading `JCLParser.g4` directly.
