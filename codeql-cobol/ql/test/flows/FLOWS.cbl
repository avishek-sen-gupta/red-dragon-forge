       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLOWS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC.
          05 A          PIC X(4).
          05 B          PIC X(6).
       01 ALT REDEFINES REC.
          05 C          PIC X(8).
       01 REC2.
          05 A2         PIC X(4).
          05 B2         PIC X(6).
       01 IN-1          PIC X(4).
       01 IN-2          PIC X(4).
       01 T             PIC X(4).
       01 U             PIC X(4).
       01 X1            PIC X(4).
       01 X2            PIC X(4).
       01 Y             PIC X(4).
       01 Z             PIC X(8).
       01 W             PIC X(8).
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT IN-1.
           ACCEPT IN-2.
           MOVE IN-1 TO T.
           PERFORM P-ID.
           MOVE U TO X1.
           DISPLAY X1.
           MOVE 'CLEAN' TO T.
           PERFORM P-ID.
           MOVE U TO X2.
           DISPLAY X2.
           MOVE IN-1 TO A.
           MOVE IN-2 TO B.
           MOVE C TO Z.
           DISPLAY Z.
           MOVE REC TO REC2.
           DISPLAY A2.
           DISPLAY B2.
           MOVE SPACES TO REC.
           MOVE C TO W.
           DISPLAY W.
           MOVE IN-2 TO T.
           GO TO P-ID.
       P-ID.
           MOVE T TO U.
       P-NEXT.
           MOVE U TO Y.
           DISPLAY Y.
           STOP RUN.
