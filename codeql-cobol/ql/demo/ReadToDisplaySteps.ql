/**
 * @name Steps of file data that reaches the job log
 * @description Each step of a path from a READ to a DISPLAY, between nodes of cobble's graph.
 * @kind table
 * @id cobol/demo/read-to-display-steps
 */

import DemoPaths

from string program, string source, string target
where Answers<ReadToDisplay>::step(program, source, target)
select program, source, target
