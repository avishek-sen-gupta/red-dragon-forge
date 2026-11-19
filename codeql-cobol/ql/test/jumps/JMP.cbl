       IDENTIFICATION DIVISION.
       PROGRAM-ID. JMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 PGM           PIC X(8) VALUE 'NEXTPGM'.
       01 TID           PIC X(4) VALUE 'T001'.
       01 AREA-1.
          05 A1         PIC X(2).
          05 A2         PIC X(2).
       LINKAGE SECTION.
       01 DFHCOMMAREA   PIC X(4).
       PROCEDURE DIVISION.
       MAIN.
           MOVE 'AB' TO A1.
           MOVE 'Z' TO A1(2:1).
           IF A2 = 'XY'
               EXEC CICS XCTL PROGRAM(PGM) COMMAREA(AREA-1) END-EXEC
           END-IF.
           CALL 'SUB' USING AREA-1.
           EXEC CICS RETURN TRANSID(TID) COMMAREA(AREA-1) END-EXEC.
