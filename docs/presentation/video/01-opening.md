# 1. Opening: the problem

**On screen:** the CardDemo source tree (`vendor/carddemo/app/cbl`, `cpy`, `jcl`, `bms`), then one
program open, e.g. `COACTUPC.cbl`, scrolled quickly.

**Talking points**
- A legacy system is thousands of lines of COBOL, copybooks, JCL and screen maps, written over
  decades by people who have left. CardDemo is small (about 30 programs) and already hard to
  hold in your head.
- The questions people actually ask are about data, not syntax: where does this number on the
  screen come from? Who changes it? If I change this field, what breaks?
- Reading the code answers them slowly, and grep answers them wrongly: names lie, values travel
  through shared buffers and between programs, and one field is often several names for the same
  bytes.
- "Just ask an LLM" reads the same names a human does. It is fluent, and it is guessing.
- The approach in this video: build the facts first, with tools that are deterministic and
  checkable. Then let the LLM interpret the facts.

**Show the difference in one example** (no tools yet): open `COTRN02C.cbl` and point at
`CDEMO-CT02-TRN-SELECTED`. By name it is a transaction id. Segment 4 shows the artifacts proving
it carries a card number in this program.
