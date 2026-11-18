"""The hand-written part of cobol.dbscheme: files, locations, programs, the layout cells, and the answers cobble gives about the generated nodes."""

PREAMBLE = """\
sourceLocationPrefix(string prefix: string ref);

files(unique int id: @file, string name: string ref);
folders(unique int id: @folder, string name: string ref);
@container = @file | @folder;
containerparent(int parent: @container ref, unique int child: @container ref);

locations_default(
  unique int id: @location_default,
  int file: @file ref,
  int beginLine: int ref,
  int beginColumn: int ref,
  int endLine: int ref,
  int endColumn: int ref
);

programs(unique int id: @program, string name: string ref, int location: @location_default ref);

/* One row per storage cell: an occurrence of a declared item, placed in its record. */
fields(
  unique int id: @field,
  int program: @program ref,
  string name: string ref,
  string record: string ref,
  int start: int ref,
  int length: int ref,
  int location: @location_default ref
);
numeric_fields(unique int field: @field ref);

/* The procedure division as the parser types it: statements before any section or
   paragraph, then the sections, then the paragraphs outside any section. The tables
   after this part mirror the parser's dataclasses. */
program_statements(int program: @program ref, int index: int ref, int statement: @cobol_statement ref);
program_sections(int program: @program ref, int index: int ref, int section: @cobol_section ref);
program_paragraphs(int program: @program ref, int index: int ref, int paragraph: @cobol_paragraph ref);

/* The units a program runs, in declaration order: the program for the statements
   before any section or paragraph, a section for the statements at its head, and each
   paragraph. A duplicate paragraph name is renamed, as cobble's paragraph order does. */
@cobol_unit = @program | @cobol_section | @cobol_paragraph;
/* What holds a list of statements: a unit, or a statement nesting others. */
@cobol_body = @cobol_unit | @cobol_statement;
units(
  int program: @program ref,
  int index: int ref,
  unique int unit: @cobol_unit ref,
  string name: string ref,
  string section: string ref
);

/* cobble's answers about generated nodes. */
/* The cells a data name denotes: every one of that name whose qualification path holds
   the qualifiers written, so a subscripted name denotes every occurrence. */
names_cell(int node: @cobol_ast_node ref, int cell: @field ref);
/* The first and last unit an out-of-line PERFORM runs. */
perform_range(int perform: @cobol_perform_statement ref, int first: @cobol_unit ref, int last: @cobol_unit ref);
/* The unit a procedure name denotes: a paragraph so named, else a section's first. */
procedure_unit(int target: @cobol_procedure_ref ref, int unit: @cobol_unit ref);
"""
