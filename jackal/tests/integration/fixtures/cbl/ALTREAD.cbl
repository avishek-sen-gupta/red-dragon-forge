       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALTREAD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT XREF-FILE ASSIGN TO XREFDD
                  ORGANIZATION IS INDEXED
                  ACCESS MODE IS SEQUENTIAL
                  RECORD KEY IS XREF-ALT.
           SELECT OUT-FILE ASSIGN TO OUTDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  XREF-FILE.
       01  XREF-REC.
           05  XREF-KEY  PIC X(3).
           05  XREF-ALT  PIC X(3).
           05  XREF-TAIL PIC X(2).
       FD  OUT-FILE.
       01  OUT-REC      PIC X(8).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT XREF-FILE.
           OPEN OUTPUT OUT-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ XREF-FILE NEXT
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE XREF-REC TO OUT-REC
                       WRITE OUT-REC
               END-READ
           END-PERFORM.
           CLOSE XREF-FILE.
           CLOSE OUT-FILE.
           GOBACK.
