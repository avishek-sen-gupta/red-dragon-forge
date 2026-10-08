# cobble: pre-flight diagnoses

Three read-only reports on what a corpus parse will fail on, run before the parse. Each takes
the corpus config. JSON goes to stdout or `--output`; a summary goes to stderr. The exit status
is 0 whatever they find.

The JSON names corpus members and quotes corpus source. Use `--output` rather than a shared
terminal. The stderr summaries name no members.

Code: `cobble/cobble/diagnosis/`.

## diagnose-copybooks

```
diagnose-copybooks --config CONFIG [--output OUTPUT] [--fix DIR]
```

Which `COPY` statements the parser will not resolve, found by scanning the `COPY` statements
instead of parsing. No JVM.

Resolution matches ProLeap's: a candidate matches when its full file name equals the copy name,
or `<name>.<ext>` for a configured `copybook_extensions` entry, ignoring case. `copybook_dirs`
are listed non-recursively. The knowledge graph's index is looser, so a copybook can have a
file location in the graph and still fail the parse.

The JSON maps each missing name to the programs that copy it and the lines of those `COPY`
statements.

`--fix DIR` writes a stub copybook into DIR for every missing name. A stub is three comment
lines saying what it is. It gets the parse past the `COPY`; the records and fields the real
copybook declared are absent. Two refusals:

- A name already on disk under an unlisted extension is not stubbed. Add the extension to
  `copybook_extensions` instead.
- A DIR outside the config's `copybook_dirs` is refused before anything is written, with exit
  status 2. A listed DIR that does not exist yet is created.

## diagnose-cobol

```
diagnose-cobol --config CONFIG [--output OUTPUT] [--max-workers N]
```

Requires `PROLEAP_BRIDGE_JAR`. Runs the parse with the same bridge, copybook flags and
parallelism as `cobble-parse-corpus`, keeps going past every rejection, and writes no cache.

Failures are grouped by signature: the parser's exception line with quoted source text and
line and column numbers removed. The summary logs signatures and counts; the JSON holds full
messages. `--max-workers` defaults to 4.

Run it after `cobble-sym`. It does not check `copybook_dirs`, so a missing directory shows as a
`NullPointerException` on every member (red-dragon-forge-gdf).

## diagnose-jcl

```
diagnose-jcl --config CONFIG [--output OUTPUT] [--max-workers N]
```

Requires `JCL_BRIDGE_JAR`. Runs the build's JCL parse phase and stops. Prints members parsed,
members failed, steps and DDs. A grammar change that recovers members must leave every member
that already parsed with the same step and DD counts; compare two runs to check.
`--max-workers` defaults to 4.
