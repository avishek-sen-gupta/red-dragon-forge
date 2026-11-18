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

/* The control-flow graph cobble's fixpoint walks, with cobble's node ids and edge
   kinds (FLOW, TRUE, FALSE, PERFORM, RETURN, FALLTHRU, GOTO). A statement lowers to
   one node, and maybe to others named by a suffix on its id: a loop's #init and
   #step, a test, an arm. */
cfg_nodes(
  unique int id: @cfg_node,
  int program: @program ref,
  string node: string ref,
  string kind: string ref,
  int location: @location_default ref
);
cfg_edges(int source: @cfg_node ref, int target: @cfg_node ref, string kind: string ref);
cfg_entry(unique int program: @program ref, int node: @cfg_node ref);
/* A PERFORM: the label its range starts at and the node the range ends at. */
cfg_call(int call: @cfg_node ref, int first: @cfg_node ref, int last: @cfg_node ref);
/* Where control goes once a PERFORM's range returns: the call has no edge there. */
cfg_resume(unique int call: @cfg_node ref, int resume: @cfg_node ref);
/* cobble's id for every statement, whether or not it lowers to a node of that id. */
statement_ids(unique int statement: @cobol_statement ref, string id: string ref);
cfg_statement(unique int node: @cfg_node ref, int statement: @cobol_statement ref);
cfg_site(unique int node: @cfg_node ref, int statement: @cobol_statement ref, string suffix: string ref);

/* cobble's answers about generated nodes. */
/* The cells a data name denotes: every one of that name whose qualification path holds
   the qualifiers written, so a subscripted name denotes every occurrence. */
names_cell(int node: @cobol_ast_node ref, int cell: @field ref);
/* A name whose bytes are located only approximately, as cobble's dataflow locates
   them: a computed subscript or reference-modification bound. A write through it
   may leave what it does not reach. */
names_clamped(unique int node: @cobol_ast_node ref);
/* The bytes of a cell a constant reference modification names: from `offset` within
   the cell, `length` of them. */
names_slice(int node: @cobol_ast_node ref, int cell: @field ref, int offset: int ref, int length: int ref);
/* The cells a name a node holds as text denotes: a WRITE's record name, an XML
   GENERATE's names, the symbolic input record (`map_input`) a RECEIVE MAP with no
   INTO fills. */
field_names_cell(int node: @cobol_ast_node ref, string field: string ref, int cell: @field ref);
/* The cells a READ or RETURN fills besides INTO: every 01 record of its file, which
   share the record area. */
file_record_cell(int read: @cobol_statement ref, int cell: @field ref);
/* The cells a SET ... TO TRUE moves its conditions' first values into, when every
   condition name it sets resolves to one declaration. */
condition_set_cell(int set: @cobol_set_statement ref, int cell: @field ref);
/* The elementary cells an INITIALIZE sets: its operands' items, but FILLERs and the
   items under a REDEFINES below an operand. */
initialized_cell(int initialize: @cobol_initialize_statement ref, int cell: @field ref);
/* The first and last unit an out-of-line PERFORM runs. */
perform_range(int perform: @cobol_perform_statement ref, int first: @cobol_unit ref, int last: @cobol_unit ref);
/* The unit a procedure name denotes: a paragraph so named, else a section's first. */
procedure_unit(int target: @cobol_procedure_ref ref, int unit: @cobol_unit ref);
"""
