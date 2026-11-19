       IDENTIFICATION DIVISION.
       PROGRAM-ID. LNKA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM        PIC X(8).
       01 WS-BACK       PIC X(8).
       01 WS-AREA.
          05 WS-NEXT    PIC X(8).
          05 WS-DATA    PIC X(4).
       LINKAGE SECTION.
       01 DFHCOMMAREA   PIC X(12).
       PROCEDURE DIVISION.
       MAIN.
           MOVE 'LNKB' TO WS-PGM.
           MOVE 'LNKD' TO WS-NEXT.
           MOVE DFHCOMMAREA(9:4) TO WS-DATA.
           CALL 'LNKC' USING WS-BACK.
           IF WS-DATA = 'X'
               EXEC CICS XCTL PROGRAM(WS-BACK) END-EXEC
           END-IF.
           IF WS-DATA = 'Y'
               EXEC CICS START TRANSID('T003') FROM(WS-AREA) END-EXEC
           END-IF.
           EXEC CICS XCTL PROGRAM(WS-PGM) COMMAREA(WS-AREA) END-EXEC.
