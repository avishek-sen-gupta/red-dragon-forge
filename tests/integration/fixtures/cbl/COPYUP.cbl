       IDENTIFICATION DIVISION.
       PROGRAM-ID. COPYUP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO INDD
                  ORGANIZATION IS SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO OUTDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC   PIC X(5).
       FD  OUT-FILE.
       01  OUT-REC  PIC X(5).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           OPEN OUTPUT OUT-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE FUNCTION UPPER-CASE(IN-REC) TO OUT-REC
                       WRITE OUT-REC
               END-READ
           END-PERFORM.
           CLOSE IN-FILE.
           CLOSE OUT-FILE.
           GOBACK.
