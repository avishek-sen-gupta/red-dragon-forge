       IDENTIFICATION DIVISION.
       PROGRAM-ID. DSNTIAC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG            PIC X(720) VALUE SPACES.
       01 WS-MSG-LEN        PIC S9(4) COMP VALUE 0.
       01 WS-PTR            PIC S9(4) COMP VALUE 1.
       01 WS-LINE-WIDTH     PIC S9(4) COMP VALUE 0.
       01 WS-LINES          PIC S9(4) COMP VALUE 0.
       01 WS-ODD-BYTES      PIC S9(4) COMP VALUE 0.
       01 WS-NEEDED         PIC S9(4) COMP VALUE 0.
       01 WS-ERRM-LEN       PIC S9(4) COMP VALUE 0.
       01 WS-ABS-SQLCODE    PIC S9(9) COMP VALUE 0.
       01 WS-DIGITS         PIC ----9.
       01 WS-SIGN           PIC X VALUE '+'.
       01 WS-USABLE         PIC X VALUE 'Y'.
      *    The text area's declared size, from CSDB2RWY.cpy's ten PIC X(72)
      *    lines. A constant, NOT read from the caller's MESG-LEN: COTRTLIC
      *    INITIALIZEs the group holding it, storing ZERO over the copybook's
      *    VALUE +720, so MESG-LEN arrives as 0. LRECL is the one field the
      *    caller sets on the way in -- CSDB2RPY.cpy MOVEs +72 into it
      *    immediately before the CALL -- so LRECL is what this stub trusts.
       01 WS-CAPACITY       PIC S9(4) COMP VALUE 720.
       LINKAGE SECTION.
      *    Sizes here must match the CALLER's argument sizes byte for byte:
      *    red-dragon packs CALL USING arguments into one buffer at cumulative
      *    offsets and the callee reads that buffer through its OWN LINKAGE
      *    offsets, so an under-declared argument shifts every later one. See
      *    squall.db2_stubs for how a mismatch is caught rather than suffered.
       01 LS-EIB            PIC X(87).
       01 LS-COMMAREA       PIC X(32767).
       01 LS-SQLCA.
          05 LS-SQLCAID     PIC X(8).
          05 LS-SQLCABC     PIC S9(9) COMP.
          05 LS-SQLCODE     PIC S9(9) COMP.
          05 LS-SQLERRM.
             49 LS-SQLERRML PIC S9(4) COMP.
             49 LS-SQLERRMC PIC X(70).
          05 LS-SQLERRP     PIC X(8).
          05 LS-SQLERRD     OCCURS 6 TIMES PIC S9(9) COMP.
          05 LS-SQLWARN     PIC X(8).
          05 LS-SQLEXT      PIC X(8).
       01 LS-FORMATTED.
          05 LS-MESG-LEN    PIC S9(4) COMP.
          05 LS-TEXT        PIC X(720).
       01 LS-LRECL          PIC S9(4) COMP.
       PROCEDURE DIVISION USING LS-EIB LS-COMMAREA LS-SQLCA
                                LS-FORMATTED LS-LRECL.
           MOVE 0 TO RETURN-CODE
           MOVE 'Y'          TO WS-USABLE
           MOVE LS-LRECL     TO WS-LINE-WIDTH
           MOVE LS-SQLERRML  TO WS-ERRM-LEN

      *    A line wider than the buffer, or an SQLERRM length outside the
      *    VARCHAR that declares it, means this stub is not reading what it
      *    thinks it is -- most likely a caller whose argument sizes differ
      *    from the LINKAGE above. Refuse rather than format noise.
           IF WS-LINE-WIDTH < 1
               MOVE 'N' TO WS-USABLE
           END-IF
           IF WS-LINE-WIDTH > WS-CAPACITY
               MOVE 'N' TO WS-USABLE
           END-IF
           IF WS-ERRM-LEN < 0
               MOVE 'N' TO WS-USABLE
           END-IF
           IF WS-ERRM-LEN > 70
               MOVE 'N' TO WS-USABLE
           END-IF

           IF WS-USABLE = 'Y'
               PERFORM 1000-BUILD-MESSAGE
               PERFORM 2000-SIZE-THE-LINES
           END-IF

           IF WS-USABLE = 'Y'
               PERFORM 3000-PLACE-THE-LINES
           ELSE
               PERFORM 9000-REFUSE-TO-FORMAT
           END-IF

           EXIT PROGRAM.

       1000-BUILD-MESSAGE.
           MOVE SPACES TO WS-MSG
           MOVE 1      TO WS-PTR
           MOVE '+'    TO WS-SIGN
           IF LS-SQLCODE < 0
               MOVE '-' TO WS-SIGN
           END-IF
           COMPUTE WS-ABS-SQLCODE = FUNCTION ABS(LS-SQLCODE)
           MOVE WS-ABS-SQLCODE TO WS-DIGITS
           STRING 'DSNTIAC: SQLCODE='
                  WS-SIGN
                  FUNCTION TRIM(WS-DIGITS)
                  DELIMITED BY SIZE
             INTO WS-MSG WITH POINTER WS-PTR
           END-STRING
           IF WS-ERRM-LEN > 0
               STRING ' '
                      LS-SQLERRMC(1:WS-ERRM-LEN)
                      DELIMITED BY SIZE
                 INTO WS-MSG WITH POINTER WS-PTR
               END-STRING
           END-IF
           COMPUTE WS-MSG-LEN = WS-PTR - 1
           .

       2000-SIZE-THE-LINES.
           DIVIDE WS-MSG-LEN BY WS-LINE-WIDTH
               GIVING WS-LINES REMAINDER WS-ODD-BYTES
           IF WS-ODD-BYTES > 0
               ADD 1 TO WS-LINES
           END-IF
           IF WS-LINES < 1
               MOVE 1 TO WS-LINES
           END-IF
           COMPUTE WS-NEEDED = WS-LINES * WS-LINE-WIDTH
           IF WS-NEEDED > WS-CAPACITY
               MOVE 'N' TO WS-USABLE
           END-IF
           .

       3000-PLACE-THE-LINES.
           MOVE SPACES TO LS-TEXT
           MOVE WS-MSG(1:WS-NEEDED) TO LS-TEXT(1:WS-NEEDED)
           MOVE WS-MSG-LEN TO LS-MESG-LEN
           .

      *    RETURN-CODE is set for a caller that can read it, but the string
      *    left in the buffer is what a caller actually sees: each program
      *    gets its own SPECIAL_REGISTERS region, so a callee's RETURN-CODE
      *    never reaches its caller (red-dragon-ltq6). Keep both -- the
      *    string makes the refusal visible today, RETURN-CODE makes it
      *    correct once ltq6 lands.
       9000-REFUSE-TO-FORMAT.
           MOVE 12 TO RETURN-CODE
           DISPLAY 'DSNTIAC STUB: CANNOT FORMAT -- LRECL=' LS-LRECL
                   ' SQLERRML=' LS-SQLERRML
                   ' (ARGUMENTS ARE NOT THE SHAPE THIS STUB READS)'
           MOVE 'DSNTIAC STUB: CANNOT FORMAT DB2 MESSAGE' TO LS-TEXT
           .
