       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 PGM           PIC X(8) VALUE 'SUBPGM'.
       01 NAME          PIC X(4).
       01 RIGHT-NAME    PIC X(10) JUSTIFIED RIGHT.
       01 N             PIC 9(2).
       01 COPY-LK       PIC X(4).
       01 STAT          PIC X(2).
       01 IO            PIC X(2).
       01 G.
          05 G-A        PIC X(1).
          05 G-B        PIC X(1) VALUE 'Z'.
       01 KEPT          PIC X(4).
       01 SRC2          PIC X(1).
       01 DST2          PIC X(1).
       LINKAGE SECTION.
       01 LK            PIC X(4).
       PROCEDURE DIVISION USING LK.
       MAIN.
           MOVE 'AB' TO NAME.
           DISPLAY NAME.
           MOVE PGM TO RIGHT-NAME.
           DISPLAY RIGHT-NAME.
           MOVE 1 TO N.
           DISPLAY N.
           MOVE LK(1:N) TO COPY-LK.
           DISPLAY COPY-LK.
           MOVE STAT TO IO.
           DISPLAY IO.
           MOVE 'X' TO G-A.
           DISPLAY G.
           PERFORM KEEP.
           DISPLAY KEPT.
           IF N = 1
               MOVE 'Q' TO SRC2
           END-IF.
           MOVE SRC2 TO DST2.
           DISPLAY DST2.
           GOBACK.
       KEEP.
           IF N = 1
               MOVE 'KEEP' TO KEPT
           END-IF.
