# Section 4 — RedDragon engine: verified facts

All paths are relative to `vendor/red-dragon/` unless they start with a package name
(`cicada/`, `squall/`, `jackal/`, `red_dragon_forge/`). Verified 2026-09-14.

## Pipeline stages

Source → frontend (parse + lower) → flattened three-address IR → CFG → function registry →
deterministic VM. Source: `README.md` "How it works"; the COBOL path is
`interpreter/run.py:1290-1301` (`compile_cobol` → `merged_ir` → `merged_cfg` →
`merged_registry`), then `run_linked` (`interpreter/run.py:1380`).

COBOL front half: ProLeap parser (Java bridge JAR) → JSON ASG → Python ASG dataclasses →
`CobolFrontend` lowering. DATA DIVISION becomes byte-addressed memory regions
(`ALLOC_REGION` + PIC-driven encode/`WRITE_REGION`); PROCEDURE DIVISION is lowered
statement by statement. Source: `docs/frontend-design/cobol.md` "Architecture",
"Data Division Lowering".

Captured run of a 21-line COBOL program: 985 IR instructions, 11 CFG blocks, 2 registry
functions, correct output. Details in `pipeline.txt`.

## IR opcode count: 37 (counted in the code)

`interpreter/ir.py:25` `class Opcode(str, Enum)` has **37 members**, counted by regex
over the enum body. Groups as commented in the file:
- value producers (13): CONST, LOAD_VAR, LOAD_FIELD, LOAD_INDEX, NEW_OBJECT, NEW_ARRAY,
  BINOP, UNOP, CALL_FUNCTION, CALL_METHOD, CALL_UNKNOWN, CALL_CTOR, CALL_WITH_MEMORY
- consumers and control flow (11): DECL_VAR, STORE_VAR, STORE_FIELD, STORE_INDEX,
  BRANCH_IF, BRANCH, RETURN, THROW, HALT, TRY_PUSH, TRY_POP
- special (1): SYMBOLIC
- byte-addressed regions (3): ALLOC_REGION, WRITE_REGION, LOAD_REGION
- named continuations (2): SET_CONTINUATION, RESUME_CONTINUATION (COBOL PERFORM return)
- cooperative suspension (1): SUSPEND
- pointers (4): ADDRESS_OF, LOAD_INDIRECT, LOAD_FIELD_INDIRECT, STORE_INDIRECT
- module import (1): IMPORT_MODULE
- pseudo-instruction (1): LABEL

This matches the README ("37-opcode universal IR").

## Language frontends

- **15 tree-sitter frontends**. Verified as the language directories under
  `interpreter/frontends/`: c, cpp, csharp, go, java, javascript, kotlin, lua, pascal, php,
  python, ruby, rust, scala, typescript. Matches `README.md` "Supported languages".
- **COBOL** through the ProLeap bridge (`interpreter/cobol/`,
  `proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar`).
- **LLM frontend** and **chunked LLM frontend** for any other language (optional).
  CLI choices: `deterministic`, `llm`, `chunked_llm` (`interpreter.py` argparse).

## COBOL feature coverage (for executives)

`interpreter/cobol/features.py` `CobolFeature` enum: **131 members, counted in the code**.
`README.md` and `docs/frontend-design/cobol.md` both say "114 enumerated features", which is
out of date. Use 131, or say "over 100". The enum lists *enumerated* features and is not a
certificate of full coverage. The gaps below still apply.

**Data representation**
- PIC/PICTURE clause, VALUE, VALUE THRU, FILLER, JUSTIFIED, SYNCHRONIZED, BLANK WHEN ZERO,
  SIGN LEADING/TRAILING, level-66 RENAMES, level-88 conditions (incl. THRU ranges,
  SET 88 TO FALSE)
- Edit pictures: numeric-edited (sign, Z suppression, comma/decimal insertion) and
  alphanumeric-edited (B / 0 / `/` insertion); external floating-point PIC
- USAGE DISPLAY (zoned decimal), COMP/COMP-4/COMP-5 (binary), **COMP-3 (packed decimal)**,
  COMP-1/COMP-2 (float), INDEX
- **EBCDIC**: `interpreter/cobol/ebcdic_table.py`. The captured run decodes region bytes
  through `__bytes_to_string ... ebcdic` (see `pipeline.txt`).
- **REDEFINES** as overlays on byte-addressed regions; **OCCURS n TIMES** and
  **OCCURS DEPENDING ON**; multi-dimensional subscripts; reference modification
- Sections: WORKING-STORAGE, LOCAL-STORAGE, LINKAGE, FILE; figurative constants

**Control flow**
- IF/ELSE, EVALUATE (WHEN THRU, WHEN OTHER; ALSO per `cobol.md`)
- PERFORM: paragraph, THRU, TIMES, UNTIL, VARYING (+ AFTER), WITH TEST BEFORE/AFTER, inline
- GO TO, GO TO DEPENDING ON, ALTER, STOP RUN (HALT), GOBACK / EXIT PROGRAM (RETURN),
  CONTINUE, EXIT, EXIT PARAGRAPH / EXIT SECTION, DECLARATIVES
- Arithmetic: ADD/SUBTRACT/MULTIPLY/DIVIDE (+ REMAINDER, GIVING, ROUNDED), COMPUTE,
  ON SIZE ERROR

**String operations**
- STRING (DELIMITED BY), UNSTRING (DELIMITED BY), INSPECT TALLYING / REPLACING / CONVERTING,
  reference modification on sources and targets; intrinsic FUNCTION calls (partial)

**CALL semantics**
- CALL, CALL USING BY REFERENCE / BY CONTENT / BY VALUE, OMITTED, literal arguments,
  GIVING, CANCEL, ENTRY
- Lowering: a fresh params region is allocated, arguments are copied in, dispatch uses
  `CALL_WITH_MEMORY`, and BY REFERENCE copies back after return (`docs/frontend-design/cobol.md`
  "Inter-program")

**File I/O**
- OPEN / CLOSE / READ (INTO, AT END) / WRITE (FROM) / REWRITE / START / DELETE, ACCEPT
- Routed through an injectable `CobolIOProvider`; `interpreter/cobol/file_drivers.py` holds
  the file-organization drivers. jackal uses `RealFileIOProvider`
  (`jackal/jackal/cobol_step.py:9`). Organisations present in the driver layer include
  keyed (KSDS-style) access and an alternate-key driver that is **read-only**
  (see gaps FACTS; forge-fh5).

**Table search** (SEARCH, WHEN, AT END, VARYING): see the SEARCH ALL finding below.

## SEARCH ALL: VERIFIED to be a linear scan, not a binary search

- `interpreter/cobol/lower_search.py` `lower_search` emits one loop. Each iteration
  evaluates the WHEN chain, adds 1 to the index, and branches back. The loop is bounded by
  the table's OCCURS count, or by `_RUNAWAY_GUARD = 4096` when the count is unknown. There
  is no midpoint, no use of the table's declared sort order, and no halving.
- `cobol_asg/cobol_statements.py:1348` `SearchStatement` has only `table`, `varying`,
  `whens`, `at_end`. There is no field for the ALL form, and the bridge emits a plain
  `newStatement("SEARCH")` (`proleap-bridge/.../StatementSerializer.java:1348`). So
  `SEARCH ALL` and `SEARCH` cannot be told apart once parsed.
- `CobolFeature.SEARCH_BINARY` exists (`features.py:91`) but is unimplemented.
- Tracked open as **forge-39r** (P3) and **red-dragon-c32s**. A linear scan returns the same
  answer for an equality WHEN over a sorted table, just slower.
  (`docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md` defect C4.)
- `docs/frontend-design/cobol.md` "SEARCH Lowering" still shows the old hard-coded 256
  bound. The code has replaced that with the OCCURS bound.
- Do **not** present SEARCH ALL as a binary search.

## Analyses

- **Type inference**: three phases (frontend extraction, `infer_types()` fixpoint, write-time
  coercion over `TypeExpr` ADTs). `README.md` "Type system"; `docs/type-system.md`.
- **Dataflow**: iterative reaching definitions, def-use chains, variable dependency graphs.
  All instruction classes expose `reads()`/`writes()`. Region opcodes are included, which
  covers COBOL. `README.md` "Dataflow analysis".
- **Interprocedural** (`interpreter/interprocedural/`): call graph (CHA), 1-CFA summaries,
  SCC fixpoint, query interfaces for **impact analysis, taint tracking and program slicing**.
  `README.md` bullet "Analyses data flow…".

## LLM usage is optional (verified in code)

- `interpreter/run_types.py:27` `unresolved_call_strategy` defaults to
  `UnresolvedCallStrategy.SYMBOLIC`. The LLM resolver is used only when
  `config.unresolved_call_strategy == UnresolvedCallStrategy.LLM` (`interpreter/run.py:143`).
  Every public `run*` signature defaults to SYMBOLIC (`interpreter/run.py:957, 1044, 1108,
  1141`).
- The COBOL path always compiles through `compile_cobol` (`interpreter/run.py:1290`), with no
  LLM frontend option. The LLM frontends are separate opt-in frontend types.
- Unresolved externals become symbolic placeholders, not LLM calls
  (`README.md` "Handling incomplete programs").
- README claim: "When source is complete and all dependencies are present, the entire pipeline
  (parse → lower → execute) is deterministic with 0 LLM calls."
- Caveat for the slide: the pipeline stats report printed "0 steps, 0 LLM calls" for the
  captured COBOL run, but `run()` does not populate either counter on the COBOL path. That
  line is not independent evidence. The evidence is structural: the default strategy is
  SYMBOLIC, no LLM client was configured, and the program still produced correct output.

## Extension seams: how CICS/SQL/JCL plug in without core VM edits

| Seam | Where defined | Contract |
|---|---|---|
| `DialectParser` (parse time) | `cobol_asg/frontend_extension.py:19` | `applies(data)` / `parse(data)` claim a coprocessor statement's bridge JSON. `NullDialectParser` is the default |
| `RedDragonExtensionLoweringStrategy` (lowering time) | `interpreter/frontend_extension_lowering.py:21` | `handles(stmt)`, `preprocess_program_dict`, `on_procedure_entry`, `lower(ctx, stmt, layout)` emit ordinary IR |
| `CoprocessorSpec` + `compile_program` (composition) | `interpreter/project/coprocessor_compile.py:38` | `name`, `make_strategy`, a source pre-scan hook, `owns_execution`, `dialect_parser`, `source_search_dirs`. All pre-scans run before any strategy is built. The module imports nothing CICS- or SQL-specific (its docstring says so) |

Implementations:
- **CICS (cicada)**: `CicsDialectParser` `cicada/cics/statements.py:37`;
  `CicsLoweringStrategy` `cicada/cics/strategy.py:541`; spec built in
  `cicada/cics/coprocessor.py` (named `cics`, a CICS source pre-scan,
  `owns_execution=True`, extra source dir for Language Environment stubs); compiled via
  `compile_program` at `cicada/cics/bootstrap.py:56`.
- **SQL (squall)**: `SqlDialectParser` `squall/squall/statements.py:25`;
  `SqlLoweringStrategy` `squall/squall/strategy.py:63`; spec in
  `squall/squall/coprocessor.py:53` (`name="sql"`, `owns_execution=False`, DCLGEN prepass).
- **Composition (forge)**: `red_dragon_forge/run.py` dispatches to the one spec that owns
  execution and asserts "at most one CoprocessorSpec may own execution".
- **JCL (jackal)** does not use a coprocessor spec. It is a driver *around* the VM: each COBOL
  step is compiled with `compile_cobol` (`jackal/jackal/cobol_step.py:14`), files go through
  the injectable `RealFileIOProvider` I/O seam, and the return code is read back with
  `read_return_code` (`cobol_step.py:11`).
- Evidence that extensions avoid core VM changes: the CICS HANDLE CONDITION dispatcher was
  built as a comparison cascade because `BranchIf` is strictly two-way. The analysis doc
  notes "following it meant no change to red-dragon's VM"
  (`docs/analysis/2026-09-01-...md`, Step 8 findings).
- Honest nuance: some general-purpose primitives that extensions rely on do live in the core
  IR (`SUSPEND` for conversational CICS, `CALL_WITH_MEMORY`, `HALT`). They are
  language-neutral opcodes, not CICS/SQL code. Also, `vendor/red-dragon` is "never modified
  here" (root `CLAUDE.md`). Both statements are true, but the first means the core did grow
  generic primitives over time.

## Existing RedDragon deck styling (`presentation/*.html`)

Both `overview-presentation.html` and `technical-presentation.html` use:
- reveal.js **5.1.0** from CDN, theme **`moon`** (`reveal.js/5.1.0/theme/moon.min.css`),
  highlight plugin with `monokai`, notes plugin. The page background comes from the moon
  theme and is not redefined inline.
- CSS variables (identical in both):
  - `--accent: #4fc3f7` (light blue; most-used colour)
  - `--accent2: #81c784` (green)
  - `--accent3: #ffb74d` (amber)
  - `--accent4: #e57373` (red)
  - `--dim: #90a4ae` (blue-grey)
  - `--box-bg: rgba(34, 51, 68, 0.85)`
  - `--box-border: #4fc3f7`
- Other literals: `#37474f`, `#ffffff`; translucent tints `rgba(79,195,247,.2/.25)`,
  `rgba(129,199,132,.25)`, `rgba(255,183,77,.25)`, `rgba(0,0,0,.3)`.
- Fonts: `Helvetica, Arial, sans-serif` for text, `monospace` for code. No Google Fonts.
