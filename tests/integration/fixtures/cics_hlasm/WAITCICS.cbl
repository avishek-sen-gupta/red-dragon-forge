       IDENTIFICATION DIVISION.
       PROGRAM-ID. WAITCICS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 MVSWAIT-TIME                 PIC 9(8) COMP.
       01 WS-STAMP                     PIC X(21).
       01 WS-CLOCK REDEFINES WS-STAMP.
          05 FILLER                    PIC X(8).
          05 WS-HH                     PIC 99.
          05 WS-MM                     PIC 99.
          05 WS-SS                     PIC 99.
          05 WS-HS                     PIC 99.
          05 FILLER                    PIC X(5).
       01 WS-NOW                       PIC 9(8).
       01 WS-BEFORE                    PIC 9(8).
       01 WS-ELAPSED                   PIC S9(8).
       01 WS-MSG                       PIC X(12).
       PROCEDURE DIVISION.
           MOVE 10 TO MVSWAIT-TIME.
           PERFORM READ-CLOCK.
           MOVE WS-NOW TO WS-BEFORE.
           CALL 'MVSWAIT' USING MVSWAIT-TIME.
           PERFORM READ-CLOCK.
           COMPUTE WS-ELAPSED = WS-NOW - WS-BEFORE.
           IF WS-ELAPSED >= MVSWAIT-TIME
               MOVE 'WAITED' TO WS-MSG
           ELSE
               MOVE 'DID NOT WAIT' TO WS-MSG
           END-IF.
           EXEC CICS SEND TEXT FROM(WS-MSG) END-EXEC.
           EXEC CICS RETURN END-EXEC.
       READ-CLOCK.
           MOVE FUNCTION CURRENT-DATE TO WS-STAMP.
           COMPUTE WS-NOW =
               ((WS-HH * 60 + WS-MM) * 60 + WS-SS) * 100 + WS-HS.
