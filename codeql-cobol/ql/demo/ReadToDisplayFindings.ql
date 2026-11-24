/**
 * @name File data that reaches the job log
 * @description Each READ whose data reaches a DISPLAY, with the file read and the fields displayed.
 * @kind table
 * @id cobol/demo/read-to-display-findings
 */

import DemoPaths

from Generated::ReadStatement read, Generated::DisplayStatement display
where Answers<ReadToDisplay>::flow(read, display)
select unitOf(read).getProgram().getName() as program, "READ " + read.getFileName() as source,
  unitOf(read).getName() as read_paragraph,
  "DISPLAY " + concat(Field f | f = display.(Stmt).getARead() | f.getName(), ", ") as sink,
  unitOf(display).getName() as display_paragraph
