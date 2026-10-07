       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYNPERFD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC-00.
           05  WS-R00-G00.
               10  WS-R00-F000  PIC X(4).
               10  WS-R00-F001  PIC X(8).
               10  WS-R00-F002  PIC X(1).
               10  WS-R00-F003  PIC X(1).
               10  WS-R00-F004  PIC X(1).
               10  WS-R00-F005  PIC 9(2).
           05  WS-R00-G01.
               10  WS-R00-F006  PIC X(8).
               10  WS-R00-F007  PIC 9(2).
               10  WS-R00-F008  PIC 9(8).
               10  WS-R00-F009  PIC 9(10).
               10  WS-R00-F010  PIC X(2).
               10  WS-R00-F011  PIC X(10).
           05  WS-R00-G02.
               10  WS-R00-F012  PIC X(10).
               10  WS-R00-F013  PIC X(1).
               10  WS-R00-F014  PIC X(1).
               10  WS-R00-F015  PIC 9(2).
               10  WS-R00-F016  PIC X(2).
               10  WS-R00-F017  PIC X(10).
           05  WS-R00-G03.
               10  WS-R00-F018  PIC X(20).
               10  WS-R00-F019  PIC X(1).
               10  WS-R00-F020  PIC 9(12).
               10  WS-R00-F021  PIC X(1).
               10  WS-R00-F022  PIC X(1).
               10  WS-R00-F023  PIC 9(10).
           05  WS-R00-G04.
               10  WS-R00-F024  PIC X(12).
               10  WS-R00-F025  PIC X(20).
               10  WS-R00-F026  PIC X(10).
               10  WS-R00-F027  PIC 9(4).
               10  WS-R00-F028  PIC X(20).
               10  WS-R00-F029  PIC X(20).
           05  WS-R00-G05.
               10  WS-R00-F030  PIC X(10).
               10  WS-R00-F031  PIC X(8).
               10  WS-R00-F032  PIC X(12).
               10  WS-R00-F033  PIC X(10).
               10  WS-R00-F034  PIC X(1).
               10  WS-R00-F035  PIC X(2).
       01  WS-RDF-00 REDEFINES WS-REC-00.
           05  WS-RDF-00-HEAD PIC X(40).
           05  WS-RDF-00-MID  PIC X(60).
           05  WS-RDF-00-TAIL PIC X(20).
       01  WS-REC-01.
           05  WS-R01-G00.
               10  WS-R01-F000  PIC X(2).
               10  WS-R01-F001  PIC 9(8).
               10  WS-R01-F002  PIC 9(12).
               10  WS-R01-F003  PIC X(10).
               10  WS-R01-F004  PIC X(20).
               10  WS-R01-F005  PIC X(12).
           05  WS-R01-G01.
               10  WS-R01-F006  PIC X(8).
               10  WS-R01-F007  PIC 9(8).
               10  WS-R01-F008  PIC X(1).
               10  WS-R01-F009  PIC X(8).
               10  WS-R01-F010  PIC 9(1).
               10  WS-R01-F011  PIC X(12).
           05  WS-R01-G02.
               10  WS-R01-F012  PIC X(10).
               10  WS-R01-F013  PIC X(20).
               10  WS-R01-F014  PIC X(12).
               10  WS-R01-F015  PIC X(12).
               10  WS-R01-F016  PIC X(8).
               10  WS-R01-F017  PIC 9(10).
           05  WS-R01-G03.
               10  WS-R01-F018  PIC 9(1).
               10  WS-R01-F019  PIC 9(4).
               10  WS-R01-F020  PIC X(2).
               10  WS-R01-F021  PIC X(20).
               10  WS-R01-F022  PIC X(2).
               10  WS-R01-F023  PIC 9(10).
           05  WS-R01-G04.
               10  WS-R01-F024  PIC X(2).
               10  WS-R01-F025  PIC X(20).
               10  WS-R01-F026  PIC X(12).
               10  WS-R01-F027  PIC X(4).
               10  WS-R01-F028  PIC X(8).
               10  WS-R01-F029  PIC 9(2).
           05  WS-R01-G05.
               10  WS-R01-F030  PIC 9(2).
               10  WS-R01-F031  PIC 9(2).
               10  WS-R01-F032  PIC X(20).
               10  WS-R01-F033  PIC 9(4).
               10  WS-R01-F034  PIC X(2).
               10  WS-R01-F035  PIC X(4).
       01  WS-REC-02.
           05  WS-R02-G00.
               10  WS-R02-F000  PIC X(4).
               10  WS-R02-F001  PIC X(12).
               10  WS-R02-F002  PIC X(10).
               10  WS-R02-F003  PIC 9(12).
               10  WS-R02-F004  PIC X(20).
               10  WS-R02-F005  PIC X(20).
           05  WS-R02-G01.
               10  WS-R02-F006  PIC X(10).
               10  WS-R02-F007  PIC X(8).
               10  WS-R02-F008  PIC X(8).
               10  WS-R02-F009  PIC 9(1).
               10  WS-R02-F010  PIC X(2).
               10  WS-R02-F011  PIC X(1).
           05  WS-R02-G02.
               10  WS-R02-F012  PIC 9(1).
               10  WS-R02-F013  PIC 9(10).
               10  WS-R02-F014  PIC X(1).
               10  WS-R02-F015  PIC 9(10).
               10  WS-R02-F016  PIC X(20).
               10  WS-R02-F017  PIC 9(8).
           05  WS-R02-G03.
               10  WS-R02-F018  PIC X(4).
               10  WS-R02-F019  PIC X(10).
               10  WS-R02-F020  PIC 9(1).
               10  WS-R02-F021  PIC X(8).
               10  WS-R02-F022  PIC X(8).
               10  WS-R02-F023  PIC 9(4).
           05  WS-R02-G04.
               10  WS-R02-F024  PIC X(1).
               10  WS-R02-F025  PIC 9(12).
               10  WS-R02-F026  PIC X(20).
               10  WS-R02-F027  PIC 9(10).
               10  WS-R02-F028  PIC X(10).
               10  WS-R02-F029  PIC X(12).
           05  WS-R02-G05.
               10  WS-R02-F030  PIC X(1).
               10  WS-R02-F031  PIC X(4).
               10  WS-R02-F032  PIC X(20).
               10  WS-R02-F033  PIC X(20).
               10  WS-R02-F034  PIC X(4).
               10  WS-R02-F035  PIC X(4).
       01  WS-REC-03.
           05  WS-R03-G00.
               10  WS-R03-F000  PIC X(10).
               10  WS-R03-F001  PIC X(10).
               10  WS-R03-F002  PIC X(2).
               10  WS-R03-F003  PIC X(20).
               10  WS-R03-F004  PIC X(20).
               10  WS-R03-F005  PIC X(2).
           05  WS-R03-G01.
               10  WS-R03-F006  PIC X(12).
               10  WS-R03-F007  PIC X(2).
               10  WS-R03-F008  PIC X(4).
               10  WS-R03-F009  PIC X(1).
               10  WS-R03-F010  PIC 9(8).
               10  WS-R03-F011  PIC X(12).
           05  WS-R03-G02.
               10  WS-R03-F012  PIC X(4).
               10  WS-R03-F013  PIC X(12).
               10  WS-R03-F014  PIC 9(4).
               10  WS-R03-F015  PIC 9(1).
               10  WS-R03-F016  PIC X(2).
               10  WS-R03-F017  PIC X(8).
           05  WS-R03-G03.
               10  WS-R03-F018  PIC X(10).
               10  WS-R03-F019  PIC X(8).
               10  WS-R03-F020  PIC X(4).
               10  WS-R03-F021  PIC X(1).
               10  WS-R03-F022  PIC X(1).
               10  WS-R03-F023  PIC X(20).
           05  WS-R03-G04.
               10  WS-R03-F024  PIC X(2).
               10  WS-R03-F025  PIC X(2).
               10  WS-R03-F026  PIC X(12).
               10  WS-R03-F027  PIC X(20).
               10  WS-R03-F028  PIC X(12).
               10  WS-R03-F029  PIC X(8).
           05  WS-R03-G05.
               10  WS-R03-F030  PIC X(1).
               10  WS-R03-F031  PIC X(2).
               10  WS-R03-F032  PIC 9(1).
               10  WS-R03-F033  PIC X(8).
               10  WS-R03-F034  PIC X(2).
               10  WS-R03-F035  PIC X(10).
       01  WS-RDF-03 REDEFINES WS-REC-03.
           05  WS-RDF-03-HEAD PIC X(40).
           05  WS-RDF-03-MID  PIC X(60).
           05  WS-RDF-03-TAIL PIC X(20).
       01  WS-TAB-00.
           05  WS-TAB-00-ENT OCCURS 20 TIMES.
               10  WS-TAB-00-KEY  PIC X(8).
               10  WS-TAB-00-AMT  PIC 9(7).
               10  WS-TAB-00-TXT  PIC X(15).
       01  WS-TAB-01.
           05  WS-TAB-01-ENT OCCURS 20 TIMES.
               10  WS-TAB-01-KEY  PIC X(8).
               10  WS-TAB-01-AMT  PIC 9(7).
               10  WS-TAB-01-TXT  PIC X(15).
       01  WS-TAB-02.
           05  WS-TAB-02-ENT OCCURS 20 TIMES.
               10  WS-TAB-02-KEY  PIC X(8).
               10  WS-TAB-02-AMT  PIC 9(7).
               10  WS-TAB-02-TXT  PIC X(15).
       01  WS-TAB-03.
           05  WS-TAB-03-ENT OCCURS 20 TIMES.
               10  WS-TAB-03-KEY  PIC X(8).
               10  WS-TAB-03-AMT  PIC 9(7).
               10  WS-TAB-03-TXT  PIC X(15).
       01  WS-TAB-04.
           05  WS-TAB-04-ENT OCCURS 20 TIMES.
               10  WS-TAB-04-KEY  PIC X(8).
               10  WS-TAB-04-AMT  PIC 9(7).
               10  WS-TAB-04-TXT  PIC X(15).
       01  WS-TAB-05.
           05  WS-TAB-05-ENT OCCURS 20 TIMES.
               10  WS-TAB-05-KEY  PIC X(8).
               10  WS-TAB-05-AMT  PIC 9(7).
               10  WS-TAB-05-TXT  PIC X(15).
       01  WS-TAB-06.
           05  WS-TAB-06-ENT OCCURS 20 TIMES.
               10  WS-TAB-06-KEY  PIC X(8).
               10  WS-TAB-06-AMT  PIC 9(7).
               10  WS-TAB-06-TXT  PIC X(15).
       01  WS-TAB-07.
           05  WS-TAB-07-ENT OCCURS 20 TIMES.
               10  WS-TAB-07-KEY  PIC X(8).
               10  WS-TAB-07-AMT  PIC 9(7).
               10  WS-TAB-07-TXT  PIC X(15).
       01  WS-TAB-08.
           05  WS-TAB-08-ENT OCCURS 20 TIMES.
               10  WS-TAB-08-KEY  PIC X(8).
               10  WS-TAB-08-AMT  PIC 9(7).
               10  WS-TAB-08-TXT  PIC X(15).
       01  WS-TAB-09.
           05  WS-TAB-09-ENT OCCURS 20 TIMES.
               10  WS-TAB-09-KEY  PIC X(8).
               10  WS-TAB-09-AMT  PIC 9(7).
               10  WS-TAB-09-TXT  PIC X(15).
       01  WS-TAB-10.
           05  WS-TAB-10-ENT OCCURS 20 TIMES.
               10  WS-TAB-10-KEY  PIC X(8).
               10  WS-TAB-10-AMT  PIC 9(7).
               10  WS-TAB-10-TXT  PIC X(15).
       01  WS-TAB-11.
           05  WS-TAB-11-ENT OCCURS 20 TIMES.
               10  WS-TAB-11-KEY  PIC X(8).
               10  WS-TAB-11-AMT  PIC 9(7).
               10  WS-TAB-11-TXT  PIC X(15).
       01  WS-CTL.
           05  WS-IX-0   PIC 9(4).
           05  WS-IX-1   PIC 9(4).
           05  WS-IX-2   PIC 9(4).
           05  WS-IX-3   PIC 9(4).
           05  WS-IX-4   PIC 9(4).
           05  WS-IX-5   PIC 9(4).
           05  WS-IX-6   PIC 9(4).
           05  WS-IX-7   PIC 9(4).
           05  WS-FLAG    PIC X(1).
           05  WS-MODE    PIC X(2).
           05  WS-COUNT   PIC 9(6).
           05  WS-PGM     PIC X(8) VALUE 'PGMNAME0'.
       PROCEDURE DIVISION.
       MAIN-LINE.
           PERFORM VARYING WS-IX-0 FROM 1 BY 1
                   UNTIL WS-IX-0 > 20
               PERFORM P0045
               MOVE WS-REC-00 TO WS-TAB-00-TXT(WS-IX-0)
           END-PERFORM
           PERFORM P0001 THRU P0080
           STOP RUN.
       P0001.
           MOVE WS-REC-00 TO WS-REC-03
           MOVE WS-R03-F026 TO WS-TAB-11-KEY(WS-IX-1)
           IF WS-FLAG = 'Y'
               GO TO P0018
           END-IF.
       P0002.
           MOVE WS-REC-00 TO WS-REC-02
           MOVE 'V' TO WS-R03-F009
           MOVE 'Z' TO WS-R02-F035(1:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-03 TO WS-REC-00
               MOVE WS-REC-01 TO WS-REC-00
               MOVE 'Z' TO WS-R00-F030(1:1)
             WHEN 'B2'
               MOVE WS-REC-00 TO WS-REC-03
               MOVE SPACES TO WS-R00-G00
               MOVE 'Q' TO WS-R00-F007
             WHEN 'C3'
               MOVE 'H' TO WS-R03-F021
               MOVE 'Q' TO WS-R01-F030
               COMPUTE WS-IX-3 = WS-IX-3 + 1
             WHEN OTHER
               MOVE SPACES TO WS-R00-G03
               MOVE 'V' TO WS-R00-F018
               MOVE 'G' TO WS-R00-F018
           END-EVALUATE.
       P0003.
           MOVE WS-R01-F028 TO WS-RDF-03-HEAD
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           IF WS-R00-F024 = SPACES
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE WS-R03-F002 TO WS-RDF-00-HEAD
               MOVE WS-R02-F035 TO WS-RDF-03-MID
           ELSE
               MOVE ZERO TO WS-R00-F023
               MOVE WS-R03-F033 TO WS-TAB-00-TXT(WS-IX-5)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0023
           END-IF.
       P0004.
           MOVE WS-R00-F001 TO WS-PGM
           CALL WS-PGM
           MOVE WS-R00-F021 TO WS-RDF-00-HEAD
           MOVE 'Y' TO WS-R00-F010
           IF WS-R00-F033 = SPACES
               MOVE WS-TAB-10-KEY(WS-IX-4) TO WS-R02-F031
               MOVE 'C' TO WS-R02-F011
               MOVE ZERO TO WS-R01-F010
           ELSE
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE WS-R00-F021 TO WS-RDF-00-MID
               MOVE WS-REC-00 TO WS-REC-01
           END-IF.
       P0005.
           MOVE 'T' TO WS-R01-F032
           MOVE SPACES TO WS-R01-G00
           MOVE WS-R01-F010 TO WS-RDF-03-HEAD
           MOVE SPACES TO WS-R02-G05
           IF WS-R01-F016 = SPACES
               MOVE 'I' TO WS-R01-F009
               MOVE 'I' TO WS-R00-F004
               MOVE WS-REC-00 TO WS-REC-02
           ELSE
               MOVE WS-REC-03 TO WS-REC-00
               MOVE WS-R03-F002 TO WS-RDF-00-TAIL
               MOVE 'Q' TO WS-R03-F031
               MOVE WS-R01-F019 TO WS-TAB-06-KEY(WS-IX-4)
           END-IF.
       P0006.
           MOVE WS-R00-F003 TO WS-RDF-00-HEAD
           MOVE WS-REC-02 TO WS-REC-01
           MOVE SPACES TO WS-R00-G05.
       P0007.
           MOVE WS-REC-01 TO WS-REC-00
           MOVE 'I' TO WS-R00-F000
           MOVE ZERO TO WS-R02-F012
           IF WS-FLAG = 'Y'
               GO TO P0003
           END-IF.
       P0008.
           MOVE WS-R00-F006 TO WS-PGM
           CALL WS-PGM
           MOVE 'I' TO WS-R03-F013
           MOVE WS-REC-01 TO WS-REC-02
           MOVE WS-R00-F022 TO WS-TAB-01-KEY(WS-IX-4)
           IF WS-R00-F005 = ZERO
               MOVE ZERO TO WS-R01-F023
               MOVE WS-REC-01 TO WS-REC-02
               COMPUTE WS-IX-6 = WS-IX-6 + 1
           ELSE
               MOVE WS-R02-F000 TO WS-TAB-07-KEY(WS-IX-2)
               MOVE WS-TAB-08-KEY(WS-IX-6) TO WS-R03-F021
               MOVE WS-R01-F022 TO WS-TAB-09-KEY(WS-IX-0)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0012
           END-IF.
       P0009.
           MOVE 'Z' TO WS-R03-F028(4:1)
           MOVE WS-REC-03 TO WS-REC-00
           PERFORM P0077 THRU P0077.
       P0010.
           MOVE WS-TAB-04-KEY(WS-IX-1) TO WS-R01-F031
           MOVE SPACES TO WS-R03-G03
           MOVE WS-TAB-01-KEY(WS-IX-7) TO WS-R02-F001
           MOVE 'Q' TO WS-R00-F019
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R02-F005(5:1)
               MOVE WS-REC-00 TO WS-REC-01
               MOVE 'W' TO WS-R00-F025
             WHEN 'B2'
               MOVE 'Z' TO WS-R02-F002(5:1)
               MOVE 'R' TO WS-R00-F030
             WHEN 'C3'
               MOVE 'P' TO WS-R00-F021
               MOVE WS-REC-03 TO WS-REC-00
             WHEN OTHER
               MOVE WS-R02-F027 TO WS-RDF-03-MID
               MOVE SPACES TO WS-R01-G00
               MOVE WS-REC-02 TO WS-REC-01
           END-EVALUATE.
       P0011.
           MOVE 'A' TO WS-R01-F004
           MOVE WS-R02-F005 TO WS-RDF-03-MID
           MOVE WS-R02-F024 TO WS-TAB-06-TXT(WS-IX-5)
           IF WS-R02-F011 = SPACES
               MOVE WS-R00-F003 TO WS-TAB-01-TXT(WS-IX-3)
               MOVE WS-REC-03 TO WS-REC-02
               MOVE WS-REC-03 TO WS-REC-01
           ELSE
               MOVE 'V' TO WS-R00-F013
               MOVE ZERO TO WS-R01-F002
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0028
           END-IF.
       P0012.
           MOVE WS-R00-F031 TO WS-PGM
           CALL WS-PGM
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE 'Z' TO WS-R00-F012(7:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE WS-REC-01 TO WS-REC-00
               MOVE 'J' TO WS-R02-F000
             WHEN 'B2'
               MOVE 'Z' TO WS-R02-F005(16:1)
               MOVE 'F' TO WS-R00-F030
               MOVE 'Q' TO WS-R00-F019
             WHEN 'C3'
               MOVE ZERO TO WS-R03-F032
               MOVE ZERO TO WS-R02-F013
             WHEN OTHER
               MOVE ZERO TO WS-R03-F032
               MOVE SPACES TO WS-R00-G01
               MOVE ZERO TO WS-R00-F023
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0031
           END-IF
           PERFORM P0065.
       P0013.
           MOVE 'G' TO WS-R03-F026
           MOVE 'Y' TO WS-R02-F014
           MOVE WS-REC-02 TO WS-REC-03.
       P0014.
           MOVE WS-REC-01 TO WS-REC-03
           MOVE 'N' TO WS-R03-F006
           IF WS-FLAG = 'Y'
               GO TO P0030
           END-IF.
       P0015.
           MOVE 'O' TO WS-R03-F027
           MOVE WS-R01-F021 TO WS-RDF-00-HEAD
           IF WS-R03-F025 = SPACES
               MOVE WS-REC-03 TO WS-REC-00
               MOVE WS-REC-00 TO WS-REC-03
               MOVE ZERO TO WS-R00-F009
               MOVE 'Z' TO WS-R02-F005(5:1)
           ELSE
               MOVE 'W' TO WS-R03-F003
               MOVE WS-R02-F004 TO WS-TAB-01-KEY(WS-IX-1)
               MOVE 'A' TO WS-R00-F000
               MOVE 'K' TO WS-R01-F035
           END-IF.
       P0016.
           MOVE WS-R01-F006 TO WS-PGM
           CALL WS-PGM
           MOVE WS-REC-03 TO WS-REC-02
           MOVE 'Q' TO WS-R00-F014
           IF WS-R03-F019 = SPACES
               MOVE 'Z' TO WS-R00-F020(5:1)
               MOVE 'L' TO WS-R03-F000
               MOVE ZERO TO WS-R00-F008
               MOVE 'Z' TO WS-R02-F035(2:1)
           ELSE
               MOVE 'Z' TO WS-R00-F001
               MOVE 'C' TO WS-R03-F021
               MOVE SPACES TO WS-R01-G02
               MOVE WS-R03-F011 TO WS-TAB-03-KEY(WS-IX-3)
           END-IF
           PERFORM P0056 THRU P0059.
       P0017.
           MOVE SPACES TO WS-R01-G03
           MOVE 'T' TO WS-R00-F014
           MOVE SPACES TO WS-R03-G00
           MOVE SPACES TO WS-R01-G03
           IF WS-R00-F015 = ZERO
               MOVE 'X' TO WS-R02-F008
               MOVE WS-REC-00 TO WS-REC-03
           ELSE
               MOVE SPACES TO WS-R03-G00
               MOVE 'L' TO WS-R02-F024
               MOVE WS-R00-F027 TO WS-RDF-03-HEAD
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0029
           END-IF.
       P0018.
           MOVE WS-R02-F019 TO WS-RDF-00-MID
           MOVE WS-TAB-04-KEY(WS-IX-6) TO WS-R00-F022
           MOVE SPACES TO WS-R03-G01
           MOVE 'A' TO WS-R03-F013
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R00-F008 TO WS-TAB-00-TXT(WS-IX-6)
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE SPACES TO WS-R00-G04
             WHEN 'B2'
               MOVE WS-R02-F009 TO WS-RDF-00-MID
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE WS-REC-00 TO WS-REC-03
             WHEN 'C3'
               MOVE WS-REC-03 TO WS-REC-01
               MOVE WS-R00-F033 TO WS-TAB-06-TXT(WS-IX-7)
             WHEN OTHER
               MOVE ZERO TO WS-R01-F002
               MOVE ZERO TO WS-R02-F009
               MOVE 'Z' TO WS-R00-F020(9:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0034
           END-IF.
       P0019.
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE 'G' TO WS-R00-F021
           MOVE WS-REC-03 TO WS-REC-02
           IF WS-FLAG = 'Y'
               GO TO P0039
           END-IF.
       P0020.
           MOVE WS-R01-F009 TO WS-PGM
           CALL WS-PGM
           MOVE WS-R02-F003 TO WS-TAB-10-TXT(WS-IX-1)
           MOVE ZERO TO WS-R01-F029
           MOVE WS-R01-F027 TO WS-TAB-03-KEY(WS-IX-7)
           MOVE SPACES TO WS-R01-G02
           IF WS-R01-F028 = SPACES
               MOVE WS-REC-00 TO WS-REC-02
               MOVE WS-REC-00 TO WS-REC-03
           ELSE
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE WS-R02-F003 TO WS-TAB-05-KEY(WS-IX-0)
               MOVE SPACES TO WS-R01-G00
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0035
           END-IF.
       P0021.
           MOVE WS-R02-F017 TO WS-RDF-00-TAIL
           MOVE SPACES TO WS-R02-G02
           MOVE SPACES TO WS-R01-G02
           MOVE WS-REC-01 TO WS-REC-00.
       P0022.
           MOVE WS-REC-03 TO WS-REC-02
           MOVE 'Z' TO WS-R00-F025
           IF WS-R03-F032 = ZERO
               MOVE 'Z' TO WS-R00-F023(3:1)
               MOVE ZERO TO WS-R01-F033
           ELSE
               MOVE WS-R00-F013 TO WS-RDF-03-MID
               MOVE 'N' TO WS-R02-F019
               MOVE 'U' TO WS-R02-F021
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0029
           END-IF.
       P0023.
           MOVE ZERO TO WS-R00-F023
           MOVE 'O' TO WS-R02-F021
           IF WS-FLAG = 'Y'
               GO TO P0036
           END-IF
           PERFORM P0063 THRU P0065.
       P0024.
           MOVE WS-R01-F016 TO WS-PGM
           CALL WS-PGM
           MOVE WS-REC-02 TO WS-REC-01
           MOVE SPACES TO WS-R01-G00
           MOVE WS-REC-03 TO WS-REC-00
           MOVE 'P' TO WS-R00-F011
           IF WS-R02-F027 = ZERO
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE 'Q' TO WS-R01-F020
           ELSE
               MOVE 'P' TO WS-R01-F014
               MOVE SPACES TO WS-R01-G00
               MOVE 'F' TO WS-R03-F024
               MOVE 'E' TO WS-R00-F031
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0031
           END-IF
           PERFORM P0060 THRU P0060.
       P0025.
           MOVE WS-TAB-01-TXT(WS-IX-6) TO WS-R03-F008
           MOVE 'N' TO WS-R01-F027
           MOVE 'O' TO WS-R02-F022
           MOVE WS-REC-00 TO WS-REC-03
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'F' TO WS-R03-F009
               MOVE WS-R00-F017 TO WS-TAB-06-KEY(WS-IX-1)
               MOVE 'Q' TO WS-R03-F005
             WHEN 'B2'
               MOVE 'Q' TO WS-R00-F010
               MOVE 'Q' TO WS-R00-F021
               COMPUTE WS-IX-5 = WS-IX-5 + 1
             WHEN 'C3'
               MOVE WS-REC-00 TO WS-REC-02
               MOVE WS-R00-F033 TO WS-TAB-01-TXT(WS-IX-3)
             WHEN OTHER
               MOVE 'Q' TO WS-R01-F020
               MOVE WS-REC-02 TO WS-REC-03
           END-EVALUATE.
       P0026.
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE SPACES TO WS-R03-G01
           MOVE 'Q' TO WS-R03-F021
           IF WS-R02-F023 = ZERO
               MOVE SPACES TO WS-R03-G01
               MOVE 'Z' TO WS-R01-F035(2:1)
           ELSE
               MOVE SPACES TO WS-R02-G00
               MOVE WS-R03-F007 TO WS-TAB-00-KEY(WS-IX-5)
               MOVE ZERO TO WS-R02-F023
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0045
           END-IF
           PERFORM P0048 THRU P0048.
       P0027.
           MOVE 'J' TO WS-R00-F012
           MOVE WS-TAB-04-KEY(WS-IX-4) TO WS-R02-F008
           MOVE 'T' TO WS-R02-F002
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'E' TO WS-R00-F012
               MOVE 'Z' TO WS-R00-F011(1:1)
               MOVE WS-REC-02 TO WS-REC-01
             WHEN 'B2'
               MOVE 'S' TO WS-R02-F005
               MOVE SPACES TO WS-R02-G04
             WHEN 'C3'
               MOVE SPACES TO WS-R00-G01
               MOVE 'Q' TO WS-R03-F007
               MOVE WS-REC-01 TO WS-REC-02
             WHEN OTHER
               MOVE ZERO TO WS-R01-F031
               MOVE WS-R03-F035 TO WS-RDF-00-TAIL
               COMPUTE WS-IX-7 = WS-IX-7 + 1
           END-EVALUATE.
       P0028.
           MOVE WS-R01-F028 TO WS-PGM
           CALL WS-PGM
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE WS-REC-00 TO WS-REC-01
           IF WS-R01-F004 = SPACES
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE WS-REC-01 TO WS-REC-00
           ELSE
               MOVE SPACES TO WS-R03-G04
               MOVE SPACES TO WS-R02-G00
               MOVE 'X' TO WS-R00-F012
           END-IF
           PERFORM P0056.
       P0029.
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE WS-R01-F021 TO WS-TAB-07-KEY(WS-IX-2)
           MOVE 'Z' TO WS-R00-F031(3:1)
           COMPUTE WS-IX-4 = WS-IX-4 + 1.
       P0030.
           MOVE WS-R01-F019 TO WS-RDF-03-TAIL
           MOVE WS-REC-00 TO WS-REC-03
           MOVE 'X' TO WS-R01-F024
           MOVE SPACES TO WS-R01-G05.
       P0031.
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE 'Z' TO WS-R00-F001(1:1)
           MOVE ZERO TO WS-R01-F023
           MOVE ZERO TO WS-R01-F018
           IF WS-R00-F019 = SPACES
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE WS-REC-00 TO WS-REC-03
               MOVE 'Z' TO WS-R01-F005(6:1)
               MOVE WS-R00-F010 TO WS-RDF-00-HEAD
           ELSE
               MOVE 'Q' TO WS-R00-F010
               MOVE 'Z' TO WS-R00-F011(2:1)
           END-IF.
       P0032.
           MOVE WS-R02-F007 TO WS-PGM
           CALL WS-PGM
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE WS-REC-01 TO WS-REC-00
           MOVE WS-REC-00 TO WS-REC-02
           IF WS-R02-F001 = SPACES
               MOVE WS-REC-00 TO WS-REC-02
               MOVE SPACES TO WS-R02-G02
               MOVE ZERO TO WS-R00-F005
           ELSE
               MOVE 'B' TO WS-R02-F000
               MOVE 'Z' TO WS-R02-F022(3:1)
               MOVE WS-TAB-09-KEY(WS-IX-7) TO WS-R02-F001
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0036
           END-IF.
       P0033.
           MOVE 'Z' TO WS-R00-F023(5:1)
           MOVE SPACES TO WS-R00-G04
           MOVE SPACES TO WS-R00-G00
           MOVE 'P' TO WS-R00-F024
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R01-F030
               MOVE WS-REC-02 TO WS-REC-00
               MOVE WS-R01-F006 TO WS-RDF-00-MID
             WHEN 'B2'
               MOVE WS-R03-F035 TO WS-RDF-00-MID
               MOVE WS-R02-F019 TO WS-TAB-10-KEY(WS-IX-5)
             WHEN 'C3'
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'L' TO WS-R00-F006
               MOVE SPACES TO WS-R02-G03
             WHEN OTHER
               MOVE ZERO TO WS-R01-F023
               MOVE WS-R00-F008 TO WS-RDF-00-TAIL
               MOVE 'Q' TO WS-R02-F011
           END-EVALUATE.
       P0034.
           MOVE WS-R00-F032 TO WS-TAB-09-TXT(WS-IX-3)
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE 'Y' TO WS-R02-F005
           MOVE 'Z' TO WS-R01-F003(3:1).
       P0035.
           MOVE 'F' TO WS-R00-F026
           MOVE WS-R02-F026 TO WS-RDF-00-HEAD
           IF WS-R01-F001 = ZERO
               MOVE WS-TAB-06-KEY(WS-IX-4) TO WS-R01-F014
               MOVE WS-REC-01 TO WS-REC-03
               MOVE WS-REC-03 TO WS-REC-01
           ELSE
               MOVE ZERO TO WS-R02-F003
               MOVE WS-REC-02 TO WS-REC-03
               MOVE WS-TAB-00-TXT(WS-IX-3) TO WS-R03-F002
               MOVE 'Q' TO WS-R01-F022
           END-IF.
       P0036.
           MOVE WS-R02-F008 TO WS-PGM
           CALL WS-PGM
           MOVE 'N' TO WS-R00-F025
           MOVE 'W' TO WS-R02-F030
           MOVE 'Z' TO WS-R01-F004(9:1)
           IF WS-FLAG = 'Y'
               GO TO P0050
           END-IF.
       P0037.
           COMPUTE WS-IX-5 = WS-IX-5 + 1
           MOVE WS-R00-F027 TO WS-TAB-06-KEY(WS-IX-7)
           IF WS-R01-F015 = SPACES
               MOVE 'R' TO WS-R03-F008
               MOVE SPACES TO WS-R03-G04
               MOVE WS-REC-02 TO WS-REC-03
               MOVE 'G' TO WS-R03-F008
           ELSE
               MOVE SPACES TO WS-R00-G05
               MOVE WS-R00-F014 TO WS-RDF-03-TAIL
               MOVE ZERO TO WS-R02-F025
               MOVE 'C' TO WS-R00-F003
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0049
           END-IF
           PERFORM P0057.
       P0038.
           MOVE 'H' TO WS-R03-F026
           MOVE WS-R01-F018 TO WS-RDF-03-MID
           MOVE SPACES TO WS-R00-G05
           MOVE SPACES TO WS-R01-G01
           IF WS-R02-F033 = SPACES
               MOVE WS-R02-F018 TO WS-RDF-00-MID
               MOVE WS-TAB-03-TXT(WS-IX-4) TO WS-R02-F024
               MOVE 'Q' TO WS-R03-F015
           ELSE
               MOVE WS-R01-F026 TO WS-TAB-04-TXT(WS-IX-5)
               MOVE 'Q' TO WS-R00-F021
           END-IF.
       P0039.
           MOVE WS-REC-02 TO WS-REC-00
           MOVE 'V' TO WS-R00-F003
           MOVE WS-REC-00 TO WS-REC-02
           IF WS-R00-F025 = SPACES
               MOVE SPACES TO WS-R01-G01
               MOVE WS-TAB-05-TXT(WS-IX-2) TO WS-R01-F017
               MOVE SPACES TO WS-R00-G05
               COMPUTE WS-IX-4 = WS-IX-4 + 1
           ELSE
               MOVE WS-REC-00 TO WS-REC-02
               MOVE WS-R03-F034 TO WS-TAB-10-KEY(WS-IX-1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0055
           END-IF.
       P0040.
           MOVE WS-R02-F021 TO WS-PGM
           CALL WS-PGM
           MOVE 'Z' TO WS-R01-F027(2:1)
           MOVE SPACES TO WS-R00-G01.
       P0041.
           MOVE 'V' TO WS-R02-F035
           MOVE WS-REC-02 TO WS-REC-03
           MOVE 'Q' TO WS-R00-F005
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'B' TO WS-R01-F000
               MOVE SPACES TO WS-R03-G05
             WHEN 'B2'
               MOVE 'K' TO WS-R02-F021
               MOVE 'Z' TO WS-R03-F033(2:1)
             WHEN 'C3'
               MOVE 'I' TO WS-R03-F000
               MOVE 'L' TO WS-R02-F002
               MOVE WS-TAB-06-TXT(WS-IX-5) TO WS-R03-F020
             WHEN OTHER
               MOVE WS-R02-F012 TO WS-RDF-03-HEAD
               MOVE SPACES TO WS-R02-G01
               MOVE 'Q' TO WS-R00-F022
           END-EVALUATE
           PERFORM P0077 THRU P0080.
       P0042.
           MOVE 'D' TO WS-R02-F004
           MOVE WS-REC-01 TO WS-REC-03
           MOVE 'Q' TO WS-R00-F015
           MOVE WS-R01-F001 TO WS-TAB-08-KEY(WS-IX-6)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-TAB-01-TXT(WS-IX-2) TO WS-R00-F009
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE 'Z' TO WS-R00-F035
             WHEN 'B2'
               MOVE SPACES TO WS-R00-G02
               MOVE WS-REC-00 TO WS-REC-01
               MOVE WS-REC-00 TO WS-REC-01
             WHEN 'C3'
               MOVE 'Z' TO WS-R02-F031(2:1)
               MOVE WS-REC-03 TO WS-REC-02
               MOVE 'Z' TO WS-R01-F003(8:1)
             WHEN OTHER
               MOVE 'Z' TO WS-R03-F001(1:1)
               MOVE WS-REC-00 TO WS-REC-03
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0058
           END-IF
           PERFORM P0058 THRU P0061.
       P0043.
           MOVE WS-R01-F001 TO WS-TAB-00-KEY(WS-IX-5)
           MOVE 'V' TO WS-R03-F009
           MOVE WS-R00-F008 TO WS-RDF-03-HEAD
           MOVE WS-REC-00 TO WS-REC-02
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'P' TO WS-R01-F006
               MOVE 'S' TO WS-R02-F022
               MOVE WS-R01-F001 TO WS-TAB-07-KEY(WS-IX-2)
             WHEN 'B2'
               MOVE SPACES TO WS-R03-G03
               MOVE 'I' TO WS-R03-F007
               MOVE WS-R02-F002 TO WS-TAB-09-TXT(WS-IX-5)
             WHEN 'C3'
               MOVE 'H' TO WS-R03-F001
               MOVE 'T' TO WS-R02-F024
             WHEN OTHER
               MOVE WS-R02-F010 TO WS-TAB-04-TXT(WS-IX-0)
               MOVE SPACES TO WS-R00-G02
           END-EVALUATE.
       P0044.
           MOVE WS-R02-F022 TO WS-PGM
           CALL WS-PGM
           MOVE SPACES TO WS-R03-G02
           MOVE 'Z' TO WS-R03-F033(4:1)
           MOVE WS-TAB-03-KEY(WS-IX-3) TO WS-R02-F007
           MOVE WS-REC-02 TO WS-REC-03
           IF WS-FLAG = 'Y'
               GO TO P0041
           END-IF
           PERFORM P0070.
       P0045.
           MOVE 'K' TO WS-R03-F025
           MOVE 'Z' TO WS-R01-F015(4:1)
           MOVE SPACES TO WS-R00-G01
           MOVE WS-TAB-04-TXT(WS-IX-5) TO WS-R02-F019
           IF WS-FLAG = 'Y'
               GO TO P0057
           END-IF.
       P0046.
           MOVE WS-R00-F007 TO WS-TAB-02-TXT(WS-IX-5)
           MOVE WS-REC-00 TO WS-REC-03
           MOVE WS-R01-F018 TO WS-RDF-03-TAIL
           IF WS-R01-F035 = SPACES
               MOVE WS-REC-03 TO WS-REC-02
               MOVE WS-R00-F009 TO WS-TAB-02-TXT(WS-IX-4)
               MOVE SPACES TO WS-R00-G00
           ELSE
               MOVE WS-REC-02 TO WS-REC-03
               MOVE WS-REC-03 TO WS-REC-00
           END-IF
           PERFORM P0067 THRU P0068.
       P0047.
           MOVE WS-REC-03 TO WS-REC-00
           MOVE 'L' TO WS-R01-F004
           MOVE WS-R00-F009 TO WS-RDF-00-HEAD
           MOVE WS-R03-F033 TO WS-RDF-03-HEAD
           IF WS-FLAG = 'Y'
               GO TO P0063
           END-IF
           PERFORM P0052 THRU P0054.
       P0048.
           MOVE WS-R03-F017 TO WS-PGM
           CALL WS-PGM
           MOVE WS-R03-F004 TO WS-RDF-03-TAIL
           MOVE WS-R02-F010 TO WS-TAB-01-TXT(WS-IX-7)
           IF WS-R03-F015 = ZERO
               MOVE SPACES TO WS-R01-G01
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE WS-REC-00 TO WS-REC-03
           ELSE
               MOVE WS-REC-02 TO WS-REC-03
               MOVE SPACES TO WS-R03-G00
           END-IF
           PERFORM P0053.
       P0049.
           MOVE WS-R03-F014 TO WS-RDF-03-HEAD
           MOVE WS-REC-02 TO WS-REC-00
           MOVE 'F' TO WS-R00-F014
           PERFORM P0063.
       P0050.
           MOVE 'I' TO WS-R00-F006
           MOVE ZERO TO WS-R02-F013
           MOVE WS-R00-F027 TO WS-TAB-04-TXT(WS-IX-7)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-01 TO WS-REC-02
               MOVE 'I' TO WS-R00-F030
               MOVE WS-TAB-05-KEY(WS-IX-6) TO WS-R01-F030
             WHEN 'B2'
               MOVE WS-REC-02 TO WS-REC-00
               MOVE WS-R03-F021 TO WS-RDF-00-MID
             WHEN 'C3'
               MOVE 'Z' TO WS-R00-F000
               MOVE WS-R01-F011 TO WS-TAB-08-TXT(WS-IX-4)
               COMPUTE WS-IX-3 = WS-IX-3 + 1
             WHEN OTHER
               MOVE WS-REC-01 TO WS-REC-02
               MOVE WS-TAB-11-KEY(WS-IX-2) TO WS-R01-F014
               COMPUTE WS-IX-7 = WS-IX-7 + 1
           END-EVALUATE
           PERFORM P0072.
       P0051.
           MOVE 'Z' TO WS-R01-F013(10:1)
           MOVE SPACES TO WS-R00-G05
           MOVE WS-R03-F024 TO WS-TAB-06-TXT(WS-IX-0)
           MOVE WS-TAB-07-TXT(WS-IX-1) TO WS-R00-F003
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R02-G00
               MOVE SPACES TO WS-R02-G04
             WHEN 'B2'
               MOVE WS-R03-F024 TO WS-TAB-05-KEY(WS-IX-7)
               MOVE 'Q' TO WS-R02-F010
               MOVE WS-TAB-06-KEY(WS-IX-0) TO WS-R02-F002
             WHEN 'C3'
               MOVE SPACES TO WS-R01-G00
               MOVE ZERO TO WS-R01-F010
               MOVE SPACES TO WS-R02-G02
             WHEN OTHER
               MOVE WS-TAB-04-KEY(WS-IX-0) TO WS-R03-F010
               MOVE WS-REC-00 TO WS-REC-02
               MOVE SPACES TO WS-R02-G00
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0056
           END-IF.
       P0052.
           MOVE WS-R03-F019 TO WS-PGM
           CALL WS-PGM
           MOVE SPACES TO WS-R03-G05
           MOVE 'U' TO WS-R00-F004
           IF WS-R02-F035 = SPACES
               MOVE WS-TAB-08-KEY(WS-IX-0) TO WS-R02-F029
               MOVE 'K' TO WS-R01-F025
               MOVE 'Q' TO WS-R02-F010
               MOVE WS-TAB-08-KEY(WS-IX-0) TO WS-R02-F011
           ELSE
               MOVE 'V' TO WS-R03-F000
               MOVE 'Z' TO WS-R02-F021(1:1)
               MOVE WS-REC-02 TO WS-REC-01
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0060
           END-IF
           PERFORM P0065 THRU P0068.
       P0053.
           MOVE WS-REC-00 TO WS-REC-03
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE 'Z' TO WS-R00-F009(2:1)
           IF WS-R03-F025 = SPACES
               MOVE 'J' TO WS-R00-F010
               MOVE WS-REC-02 TO WS-REC-03
           ELSE
               MOVE SPACES TO WS-R02-G00
               MOVE 'Z' TO WS-R01-F001(4:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0063
           END-IF.
       P0054.
           MOVE 'X' TO WS-R00-F022
           MOVE 'U' TO WS-R01-F020
           MOVE ZERO TO WS-R03-F032.
       P0055.
           MOVE WS-REC-02 TO WS-REC-00
           MOVE SPACES TO WS-R03-G04
           MOVE 'F' TO WS-R02-F018
           IF WS-FLAG = 'Y'
               GO TO P0064
           END-IF.
       P0056.
           MOVE WS-R03-F029 TO WS-PGM
           CALL WS-PGM
           MOVE WS-REC-00 TO WS-REC-03
           MOVE 'Z' TO WS-R02-F017(4:1)
           MOVE 'Q' TO WS-R03-F024
           IF WS-R03-F004 = SPACES
               MOVE WS-R01-F003 TO WS-TAB-01-TXT(WS-IX-3)
               MOVE 'T' TO WS-R01-F015
               MOVE 'D' TO WS-R03-F024
           ELSE
               MOVE WS-TAB-07-TXT(WS-IX-4) TO WS-R00-F032
               MOVE WS-REC-00 TO WS-REC-01
               MOVE ZERO TO WS-R01-F002
               MOVE 'T' TO WS-R01-F035
           END-IF.
       P0057.
           MOVE 'J' TO WS-R02-F018
           MOVE 'R' TO WS-R03-F026
           MOVE 'Q' TO WS-R02-F010
           IF WS-R03-F019 = SPACES
               MOVE 'R' TO WS-R01-F011
               MOVE ZERO TO WS-R01-F001
               MOVE 'S' TO WS-R02-F024
           ELSE
               MOVE WS-REC-02 TO WS-REC-01
               MOVE WS-R01-F016 TO WS-RDF-00-MID
           END-IF.
       P0058.
           MOVE WS-REC-03 TO WS-REC-01
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R02-F027 TO WS-TAB-11-TXT(WS-IX-6)
               MOVE 'A' TO WS-R03-F007
               MOVE 'Z' TO WS-R03-F026(4:1)
             WHEN 'B2'
               MOVE 'Z' TO WS-R01-F003(4:1)
               MOVE WS-R03-F004 TO WS-RDF-03-MID
               MOVE WS-R03-F027 TO WS-TAB-09-KEY(WS-IX-5)
             WHEN 'C3'
               MOVE 'J' TO WS-R00-F019
               MOVE WS-REC-02 TO WS-REC-03
               MOVE 'N' TO WS-R03-F022
             WHEN OTHER
               MOVE SPACES TO WS-R02-G04
               MOVE SPACES TO WS-R01-G03
               MOVE SPACES TO WS-R00-G02
           END-EVALUATE
           PERFORM P0059 THRU P0061.
       P0059.
           MOVE 'Z' TO WS-R00-F001(3:1)
           MOVE 'S' TO WS-R00-F025
           MOVE WS-REC-00 TO WS-REC-03
           MOVE SPACES TO WS-R02-G05.
       P0060.
           MOVE WS-R03-F033 TO WS-PGM
           CALL WS-PGM
           MOVE SPACES TO WS-R00-G00
           MOVE WS-REC-01 TO WS-REC-02
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R00-F015
               MOVE 'Q' TO WS-R02-F010
               MOVE SPACES TO WS-R01-G02
             WHEN 'B2'
               MOVE 'Q' TO WS-R00-F016
               MOVE 'T' TO WS-R03-F007
               MOVE 'H' TO WS-R00-F013
             WHEN 'C3'
               MOVE WS-REC-03 TO WS-REC-00
               MOVE 'Z' TO WS-R01-F027(1:1)
               MOVE WS-REC-01 TO WS-REC-03
             WHEN OTHER
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE 'P' TO WS-R01-F028
           END-EVALUATE
           PERFORM P0073 THRU P0074.
       P0061.
           MOVE 'A' TO WS-R03-F016
           MOVE WS-R01-F008 TO WS-TAB-03-KEY(WS-IX-1)
           MOVE SPACES TO WS-R02-G03
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R02-F013
               MOVE 'D' TO WS-R00-F016
               MOVE ZERO TO WS-R02-F017
             WHEN 'B2'
               MOVE 'O' TO WS-R01-F012
               MOVE 'N' TO WS-R01-F024
               MOVE WS-REC-00 TO WS-REC-01
             WHEN 'C3'
               MOVE 'F' TO WS-R01-F025
               MOVE ZERO TO WS-R01-F019
             WHEN OTHER
               MOVE ZERO TO WS-R01-F017
               MOVE 'Q' TO WS-R03-F013
               MOVE SPACES TO WS-R03-G05
           END-EVALUATE.
       P0062.
           MOVE 'G' TO WS-R03-F022
           MOVE SPACES TO WS-R00-G05
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R01-F001 TO WS-TAB-06-TXT(WS-IX-0)
               MOVE 'Z' TO WS-R01-F009(2:1)
               MOVE ZERO TO WS-R00-F027
             WHEN 'B2'
               MOVE 'Y' TO WS-R03-F020
               MOVE 'W' TO WS-R00-F016
             WHEN 'C3'
               MOVE WS-REC-02 TO WS-REC-00
               MOVE WS-TAB-06-TXT(WS-IX-4) TO WS-R02-F019
               MOVE 'Z' TO WS-R00-F033(5:1)
             WHEN OTHER
               MOVE WS-REC-02 TO WS-REC-01
               MOVE WS-REC-03 TO WS-REC-00
           END-EVALUATE.
       P0063.
           MOVE SPACES TO WS-R00-G02
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           IF WS-FLAG = 'Y'
               GO TO P0077
           END-IF.
       P0064.
           MOVE WS-R00-F001 TO WS-PGM
           CALL WS-PGM
           MOVE WS-TAB-08-KEY(WS-IX-4) TO WS-R01-F009
           MOVE 'Q' TO WS-R01-F029
           COMPUTE WS-IX-5 = WS-IX-5 + 1.
       P0065.
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE WS-R02-F009 TO WS-RDF-00-HEAD
           IF WS-R02-F016 = SPACES
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE 'Z' TO WS-R02-F028(4:1)
               MOVE ZERO TO WS-R00-F023
               MOVE 'O' TO WS-R03-F000
           ELSE
               MOVE 'Q' TO WS-R03-F007
               MOVE 'Z' TO WS-R01-F016(4:1)
               MOVE 'Z' TO WS-R00-F032(8:1)
           END-IF
           PERFORM P0077 THRU P0079.
       P0066.
           MOVE 'Q' TO WS-R01-F024
           MOVE WS-REC-00 TO WS-REC-03
           IF WS-R02-F033 = SPACES
               MOVE SPACES TO WS-R02-G01
               MOVE SPACES TO WS-R03-G05
           ELSE
               MOVE 'A' TO WS-R01-F025
               MOVE 'U' TO WS-R00-F034
               MOVE 'E' TO WS-R02-F004
           END-IF
           PERFORM P0076 THRU P0077.
       P0067.
           MOVE 'Z' TO WS-R00-F030(7:1)
           MOVE WS-TAB-02-TXT(WS-IX-2) TO WS-R03-F010
           MOVE WS-REC-02 TO WS-REC-00
           IF WS-R01-F016 = SPACES
               MOVE WS-REC-02 TO WS-REC-01
               MOVE SPACES TO WS-R02-G03
           ELSE
               MOVE SPACES TO WS-R03-G03
               MOVE ZERO TO WS-R01-F007
           END-IF
           PERFORM P0075 THRU P0078.
       P0068.
           MOVE WS-R00-F006 TO WS-PGM
           CALL WS-PGM
           MOVE WS-TAB-05-TXT(WS-IX-4) TO WS-R00-F027
           MOVE 'Q' TO WS-R02-F010
           IF WS-R00-F023 = ZERO
               MOVE 'U' TO WS-R01-F028
               MOVE 'X' TO WS-R00-F035
               MOVE WS-REC-03 TO WS-REC-00
               MOVE 'U' TO WS-R01-F011
           ELSE
               MOVE WS-TAB-10-TXT(WS-IX-2) TO WS-R00-F026
               MOVE 'U' TO WS-R01-F011
               MOVE WS-TAB-05-KEY(WS-IX-3) TO WS-R02-F022
               MOVE 'H' TO WS-R01-F028
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0079
           END-IF.
       P0069.
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE 'J' TO WS-R01-F004
           MOVE 'Z' TO WS-R00-F020(3:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'C' TO WS-R02-F030
               MOVE WS-R01-F012 TO WS-RDF-03-MID
             WHEN 'B2'
               MOVE WS-R03-F022 TO WS-TAB-00-TXT(WS-IX-0)
               MOVE WS-REC-00 TO WS-REC-02
             WHEN 'C3'
               MOVE 'C' TO WS-R02-F014
               MOVE 'X' TO WS-R01-F009
               MOVE SPACES TO WS-R02-G00
             WHEN OTHER
               MOVE SPACES TO WS-R00-G04
               MOVE 'N' TO WS-R03-F009
               MOVE WS-R00-F020 TO WS-RDF-00-MID
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0074
           END-IF.
       P0070.
           MOVE WS-REC-01 TO WS-REC-00
           MOVE 'Z' TO WS-R03-F006(2:1)
           MOVE SPACES TO WS-R02-G04
           MOVE ZERO TO WS-R02-F020
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'F' TO WS-R01-F022
               MOVE WS-R00-F028 TO WS-RDF-00-TAIL
               MOVE 'U' TO WS-R01-F028
             WHEN 'B2'
               MOVE SPACES TO WS-R02-G05
               MOVE 'Q' TO WS-R03-F009
             WHEN 'C3'
               MOVE 'Z' TO WS-R00-F028(17:1)
               COMPUTE WS-IX-1 = WS-IX-1 + 1
             WHEN OTHER
               MOVE 'Z' TO WS-R03-F004(5:1)
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'Z' TO WS-R03-F023(4:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0079
           END-IF.
       P0071.
           MOVE WS-REC-01 TO WS-REC-03
           MOVE WS-R01-F024 TO WS-TAB-00-KEY(WS-IX-6)
           MOVE WS-REC-01 TO WS-REC-03
           MOVE 'N' TO WS-R00-F034.
       P0072.
           MOVE WS-R00-F031 TO WS-PGM
           CALL WS-PGM
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           MOVE ZERO TO WS-R02-F015
           MOVE WS-R01-F029 TO WS-TAB-11-KEY(WS-IX-0)
           MOVE 'Z' TO WS-R02-F019(8:1)
           IF WS-R02-F018 = SPACES
               MOVE 'Z' TO WS-R02-F011
               MOVE WS-REC-01 TO WS-REC-03
           ELSE
               MOVE SPACES TO WS-R03-G00
               MOVE WS-R00-F029 TO WS-TAB-09-KEY(WS-IX-7)
               MOVE WS-REC-02 TO WS-REC-00
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0079
           END-IF.
       P0073.
           MOVE 'Z' TO WS-R01-F032(15:1)
           MOVE WS-REC-02 TO WS-REC-00
           MOVE ZERO TO WS-R00-F008
           IF WS-FLAG = 'Y'
               GO TO P0079
           END-IF.
       P0074.
           MOVE WS-R01-F022 TO WS-RDF-03-MID
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE 'G' TO WS-R03-F027
           IF WS-R00-F033 = SPACES
               MOVE 'Q' TO WS-R01-F018
               MOVE SPACES TO WS-R02-G05
               MOVE 'Z' TO WS-R03-F011(7:1)
               MOVE WS-R02-F013 TO WS-RDF-03-HEAD
           ELSE
               MOVE WS-REC-00 TO WS-REC-03
               MOVE 'Z' TO WS-R00-F011(3:1)
               MOVE WS-R02-F026 TO WS-TAB-02-TXT(WS-IX-4)
               MOVE WS-R03-F027 TO WS-RDF-03-TAIL
           END-IF
           PERFORM P0075 THRU P0075.
       P0075.
           MOVE WS-TAB-10-TXT(WS-IX-1) TO WS-R02-F020
           MOVE 'V' TO WS-R01-F000
           IF WS-R02-F015 = ZERO
               MOVE 'L' TO WS-R01-F026
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE 'V' TO WS-R02-F014
               MOVE ZERO TO WS-R03-F015
           ELSE
               MOVE 'Z' TO WS-R01-F026
               MOVE ZERO TO WS-R02-F017
               MOVE SPACES TO WS-R01-G00
               COMPUTE WS-IX-7 = WS-IX-7 + 1
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0078
           END-IF.
       P0076.
           MOVE WS-R01-F006 TO WS-PGM
           CALL WS-PGM
           MOVE 'I' TO WS-R02-F006
           MOVE WS-TAB-08-KEY(WS-IX-5) TO WS-R00-F018
           IF WS-R01-F009 = SPACES
               MOVE 'Y' TO WS-R02-F019
               MOVE 'Z' TO WS-R00-F017(8:1)
               MOVE 'I' TO WS-R01-F008
           ELSE
               MOVE WS-REC-02 TO WS-REC-00
               MOVE 'Z' TO WS-R01-F019(1:1)
               MOVE 'T' TO WS-R01-F015
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0077
           END-IF.
       P0077.
           MOVE WS-REC-00 TO WS-REC-02
           MOVE 'A' TO WS-R00-F034
           IF WS-R03-F029 = SPACES
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'U' TO WS-R00-F006
               MOVE 'Q' TO WS-R02-F014
           ELSE
               MOVE WS-REC-03 TO WS-REC-00
               MOVE WS-REC-02 TO WS-REC-01
           END-IF.
       P0078.
           MOVE WS-REC-02 TO WS-REC-03
           MOVE 'Z' TO WS-R02-F008(1:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-01 TO WS-REC-00
               MOVE SPACES TO WS-R00-G02
             WHEN 'B2'
               MOVE 'V' TO WS-R03-F029
               MOVE 'Z' TO WS-R01-F003(6:1)
               MOVE ZERO TO WS-R01-F030
             WHEN 'C3'
               MOVE WS-REC-02 TO WS-REC-03
               MOVE WS-R03-F035 TO WS-TAB-11-TXT(WS-IX-7)
               MOVE 'I' TO WS-R00-F033
             WHEN OTHER
               MOVE WS-TAB-05-TXT(WS-IX-2) TO WS-R01-F022
               MOVE WS-REC-00 TO WS-REC-02
               MOVE SPACES TO WS-R00-G04
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0079
           END-IF.
       P0079.
           MOVE 'O' TO WS-R01-F026
           MOVE WS-R02-F016 TO WS-RDF-03-HEAD
           IF WS-FLAG = 'Y'
               GO TO P0080
           END-IF.
       P0080.
           MOVE WS-R01-F009 TO WS-PGM
           CALL WS-PGM
           MOVE WS-TAB-06-KEY(WS-IX-5) TO WS-R00-F015
           MOVE 'V' TO WS-R02-F024
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R01-F031
               MOVE 'Z' TO WS-R01-F025(8:1)
             WHEN 'B2'
               MOVE SPACES TO WS-R03-G05
               MOVE 'G' TO WS-R03-F019
               MOVE WS-R01-F032 TO WS-RDF-00-MID
             WHEN 'C3'
               MOVE WS-R02-F012 TO WS-TAB-04-KEY(WS-IX-1)
               COMPUTE WS-IX-2 = WS-IX-2 + 1
             WHEN OTHER
               MOVE 'Q' TO WS-R03-F007
               MOVE SPACES TO WS-R00-G01
               MOVE WS-R00-F011 TO WS-TAB-11-TXT(WS-IX-5)
           END-EVALUATE.
