       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYNGOTOB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG  PIC X VALUE 'N'.
       01  WA  PIC X VALUE SPACE.
       01  WB  PIC X VALUE SPACE.
       01  WC  PIC X VALUE SPACE.
       01  WD  PIC X VALUE SPACE.
       01  WE  PIC X VALUE SPACE.
       01  WF  PIC X VALUE SPACE.
       PROCEDURE DIVISION.
       MAIN-LINE.
           PERFORM T.
           STOP RUN.
       T.
           PERFORM A
           PERFORM B
           PERFORM C
           PERFORM D
           PERFORM E
           PERFORM F.
       A.
           MOVE 'A' TO WA
           IF WS-FLAG = 'Y'
               GO TO T
           END-IF.
       B.
           MOVE 'B' TO WB
           IF WS-FLAG = 'Y'
               GO TO T
           END-IF.
       C.
           MOVE 'C' TO WC
           IF WS-FLAG = 'Y'
               GO TO T
           END-IF.
       D.
           MOVE 'D' TO WD
           IF WS-FLAG = 'Y'
               GO TO T
           END-IF.
       E.
           MOVE 'E' TO WE
           IF WS-FLAG = 'Y'
               GO TO T
           END-IF.
       F.
           MOVE 'F' TO WF
           IF WS-FLAG = 'Y'
               GO TO T
           END-IF.
