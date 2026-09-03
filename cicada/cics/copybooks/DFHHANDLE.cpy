      * Condition handler tables, indexed by DFHRESP code + 1
      * (COBOL OCCURS is 1-based). DFH-RAISABLE marks the conditions
      * this runtime raises; its literal is generated from
      * cics/conditions.py. HANDLE CONDITION sets it, IGNORE CONDITION
      * clears it. DFH-HANDLER holds a label index, LOW-VALUES meaning
      * none, so WORKING-STORAGE initialisation gives each program an
      * empty table and a called program cannot inherit one.
       01  DFH-RAISABLE-BYTES PIC X(37) VALUE
           'NYNNNNNNNNNNNYYYYNYYNNYNNNNNNNNNNNNNY'.
       01  DFH-RAISABLE-TAB REDEFINES DFH-RAISABLE-BYTES.
           05  DFH-RAISABLE OCCURS 37 TIMES PIC X.
       01  DFH-HANDLER-BYTES PIC X(74) VALUE LOW-VALUES.
       01  DFH-HANDLER-TAB REDEFINES DFH-HANDLER-BYTES.
           05  DFH-HANDLER OCCURS 37 TIMES PIC S9(4) COMP.
