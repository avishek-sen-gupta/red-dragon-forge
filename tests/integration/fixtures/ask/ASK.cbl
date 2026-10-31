       IDENTIFICATION DIVISION.
       PROGRAM-ID. ASK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME                      PIC X(8).
       01 WS-AGE                       PIC X(3).
       PROCEDURE DIVISION.
           DISPLAY 'NAME?'.
           ACCEPT WS-NAME.
           DISPLAY 'HELLO ' WS-NAME.
           IF WS-NAME = 'BOB'
               DISPLAY 'AGE?'
               ACCEPT WS-AGE
               DISPLAY 'AGE ' WS-AGE
           END-IF.
           STOP RUN.
