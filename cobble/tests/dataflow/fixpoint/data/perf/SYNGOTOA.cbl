       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYNGOTOA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG  PIC X VALUE 'N'.
       01  WS-F00  PIC X(4) VALUE 'INIT'.
       01  WS-F01  PIC X(4) VALUE 'INIT'.
       01  WS-F02  PIC X(4) VALUE 'INIT'.
       01  WS-F03  PIC X(4) VALUE 'INIT'.
       01  WS-F04  PIC X(4) VALUE 'INIT'.
       01  WS-F05  PIC X(4) VALUE 'INIT'.
       PROCEDURE DIVISION.
       MAIN-LINE.
           PERFORM T01 THRU C06.
           STOP RUN.
       T01.
           MOVE 'L100' TO WS-F03
           MOVE 'L101' TO WS-F04
           PERFORM B01 THRU C01
           PERFORM C01.
       B01.
           MOVE WS-F01 TO WS-F02.
       C01.
           MOVE WS-F03 TO WS-F04
           IF WS-FLAG = 'Y'
               GO TO T01
           END-IF.
       T02.
           MOVE 'L200' TO WS-F00
           MOVE 'L201' TO WS-F01
           PERFORM B02 THRU C02
           PERFORM C02.
       B02.
           MOVE WS-F02 TO WS-F03.
       C02.
           MOVE WS-F04 TO WS-F05
           IF WS-FLAG = 'Y'
               GO TO T01
           END-IF.
       T03.
           MOVE 'L300' TO WS-F03
           MOVE 'L301' TO WS-F04
           PERFORM B03 THRU C03
           PERFORM C03.
       B03.
           MOVE WS-F03 TO WS-F04.
       C03.
           MOVE WS-F05 TO WS-F00
           IF WS-FLAG = 'Y'
               GO TO T01
           END-IF.
       T04.
           MOVE 'L400' TO WS-F00
           MOVE 'L401' TO WS-F01
           PERFORM B04 THRU C04
           PERFORM C04.
       B04.
           MOVE WS-F04 TO WS-F05.
       C04.
           MOVE WS-F00 TO WS-F01
           IF WS-FLAG = 'Y'
               GO TO T01
           END-IF.
       T05.
           MOVE 'L500' TO WS-F03
           MOVE 'L501' TO WS-F04
           PERFORM B05 THRU C05
           PERFORM C05.
       B05.
           MOVE WS-F05 TO WS-F00.
       C05.
           MOVE WS-F01 TO WS-F02
           IF WS-FLAG = 'Y'
               GO TO T01
           END-IF.
       T06.
           MOVE 'L600' TO WS-F00
           MOVE 'L601' TO WS-F01
           PERFORM B06 THRU C06
           PERFORM C06.
       B06.
           MOVE WS-F00 TO WS-F01.
       C06.
           MOVE WS-F02 TO WS-F03
           IF WS-FLAG = 'Y'
               GO TO T01
           END-IF.
