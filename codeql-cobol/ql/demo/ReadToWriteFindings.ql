/**
 * @name File data that reaches another file
 * @description Each READ whose data reaches a WRITE, with the file read and the record written.
 * @kind table
 * @id cobol/demo/read-to-write-findings
 */

import DemoPaths

from Generated::ReadStatement read, Generated::WriteStatement write
where Answers<ReadToWrite>::flow(read, write)
select unitOf(read).getProgram().getName() as program, "READ " + read.getFileName() as source,
  unitOf(read).getName() as read_paragraph, "WRITE " + write.getRecordName() as sink,
  unitOf(write).getName() as write_paragraph
