       IDENTIFICATION DIVISION.
       PROGRAM-ID. CEEDAYS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-YYYY        PIC 9(4) VALUE 0.
       01 WS-MM          PIC 9(2) VALUE 0.
       01 WS-DD          PIC 9(2) VALUE 0.
       01 WS-YYYYMMDD    PIC 9(8) VALUE 0.
       01 WS-MAX-DAY     PIC 9(2) VALUE 0.
       01 WS-VALID       PIC X VALUE 'Y'.
       01 WS-R4          PIC 9(4) VALUE 0.
       01 WS-R100        PIC 9(4) VALUE 0.
       01 WS-R400        PIC 9(4) VALUE 0.
       01 WS-I           PIC 9(4) VALUE 0.
       01 WS-Y-POS       PIC 9(4) VALUE 0.
       01 WS-M-POS       PIC 9(4) VALUE 0.
       01 WS-D-POS       PIC 9(4) VALUE 0.
       LINKAGE SECTION.
       01 LS-DATE-VS.
          05 LS-DATE-LEN   PIC S9(4) BINARY.
          05 LS-DATE-TXT   PIC X(256).
       01 LS-FMT-VS.
          05 LS-FMT-LEN    PIC S9(4) BINARY.
          05 LS-FMT-TXT    PIC X(256).
       01 LS-LILIAN        PIC S9(9) BINARY.
       01 LS-FEEDBACK.
          05 LS-FB-SEV     PIC S9(4) BINARY.
          05 LS-FB-MSG     PIC S9(4) BINARY.
          05 FILLER        PIC X(8).
       PROCEDURE DIVISION USING LS-DATE-VS LS-FMT-VS
                                LS-LILIAN LS-FEEDBACK.
           MOVE 'Y' TO WS-VALID
           MOVE 0   TO LS-FB-SEV
           MOVE 0   TO LS-FB-MSG
           MOVE 0   TO LS-LILIAN

      *    The picture string says where YYYY, MM and DD sit in the date.
      *    CardDemo passes YYYYMMDD (CSUTLDPY) and YYYY-MM-DD (COTRN02C).
           MOVE 0 TO WS-Y-POS WS-M-POS WS-D-POS
           PERFORM VARYING WS-I FROM 1 BY 1
               UNTIL WS-I > LS-FMT-LEN OR WS-I > 253
               IF LS-FMT-TXT(WS-I:4) = 'YYYY'
                   MOVE WS-I TO WS-Y-POS
               END-IF
               IF LS-FMT-TXT(WS-I:2) = 'MM'
                   MOVE WS-I TO WS-M-POS
               END-IF
               IF LS-FMT-TXT(WS-I:2) = 'DD'
                   MOVE WS-I TO WS-D-POS
               END-IF
           END-PERFORM
           IF WS-Y-POS = 0 OR WS-M-POS = 0 OR WS-D-POS = 0
               MOVE 'N' TO WS-VALID
           END-IF

           IF WS-VALID = 'Y'
               IF LS-DATE-TXT(WS-Y-POS:4) IS NOT NUMERIC
               OR LS-DATE-TXT(WS-M-POS:2) IS NOT NUMERIC
               OR LS-DATE-TXT(WS-D-POS:2) IS NOT NUMERIC
                   MOVE 'N' TO WS-VALID
               END-IF
           END-IF

           IF WS-VALID = 'Y'
               MOVE LS-DATE-TXT(WS-Y-POS:4) TO WS-YYYY
               MOVE LS-DATE-TXT(WS-M-POS:2) TO WS-MM
               MOVE LS-DATE-TXT(WS-D-POS:2) TO WS-DD

               IF WS-MM < 1 OR WS-MM > 12
                   MOVE 'N' TO WS-VALID
               END-IF
               IF WS-DD < 1
                   MOVE 'N' TO WS-VALID
               END-IF

               EVALUATE WS-MM
                   WHEN 1
                   WHEN 3
                   WHEN 5
                   WHEN 7
                   WHEN 8
                   WHEN 10
                   WHEN 12
                       MOVE 31 TO WS-MAX-DAY
                   WHEN 4
                   WHEN 6
                   WHEN 9
                   WHEN 11
                       MOVE 30 TO WS-MAX-DAY
                   WHEN 2
                       COMPUTE WS-R4 = FUNCTION MOD(WS-YYYY 4)
                       COMPUTE WS-R100 = FUNCTION MOD(WS-YYYY 100)
                       COMPUTE WS-R400 = FUNCTION MOD(WS-YYYY 400)
                       IF WS-R400 = 0
                           MOVE 29 TO WS-MAX-DAY
                       ELSE
                           IF WS-R100 = 0
                               MOVE 28 TO WS-MAX-DAY
                           ELSE
                               IF WS-R4 = 0
                                   MOVE 29 TO WS-MAX-DAY
                               ELSE
                                   MOVE 28 TO WS-MAX-DAY
                               END-IF
                           END-IF
                       END-IF
                   WHEN OTHER
                       MOVE 0 TO WS-MAX-DAY
               END-EVALUATE

               IF WS-DD > WS-MAX-DAY
                   MOVE 'N' TO WS-VALID
               END-IF
           END-IF

           IF WS-VALID = 'Y'
               COMPUTE WS-YYYYMMDD =
                   (WS-YYYY * 10000) + (WS-MM * 100) + WS-DD
               COMPUTE LS-LILIAN =
                   FUNCTION INTEGER-OF-DATE(WS-YYYYMMDD)
               MOVE 0  TO LS-FB-SEV
               MOVE 0  TO LS-FB-MSG
           ELSE
               MOVE 12 TO LS-FB-SEV
               MOVE 1  TO LS-FB-MSG
           END-IF

           EXIT PROGRAM.
