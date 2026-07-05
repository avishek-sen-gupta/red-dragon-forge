       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARRER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT W-FILE ASSIGN TO WRKDD ORGANIZATION IS SEQUENTIAL.
           SELECT O-FILE ASSIGN TO OUTDD ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  W-FILE.
       01  W-REC PIC X(5).
       FD  O-FILE.
       01  O-REC PIC X(5).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT W-FILE.
           OPEN OUTPUT O-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ W-FILE
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE W-REC TO O-REC
                       MOVE '*' TO O-REC(1:1)
                       WRITE O-REC
               END-READ
           END-PERFORM.
           CLOSE W-FILE.
           CLOSE O-FILE.
           GOBACK.
