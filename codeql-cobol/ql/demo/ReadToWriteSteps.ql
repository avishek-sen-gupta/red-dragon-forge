/**
 * @name Steps of file data that reaches another file
 * @description Each step of a path from a READ to a WRITE, between nodes of cobble's graph.
 * @kind table
 * @id cobol/demo/read-to-write-steps
 */

import DemoPaths

from string program, string source, string target
where Answers<ReadToWrite>::step(program, source, target)
select program, source, target
