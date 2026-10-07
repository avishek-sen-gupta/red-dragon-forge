       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYNPERFC.
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
       01  WS-REC-04.
           05  WS-R04-G00.
               10  WS-R04-F000  PIC X(12).
               10  WS-R04-F001  PIC X(2).
               10  WS-R04-F002  PIC 9(2).
               10  WS-R04-F003  PIC X(20).
               10  WS-R04-F004  PIC 9(12).
               10  WS-R04-F005  PIC X(12).
           05  WS-R04-G01.
               10  WS-R04-F006  PIC X(8).
               10  WS-R04-F007  PIC X(2).
               10  WS-R04-F008  PIC 9(2).
               10  WS-R04-F009  PIC 9(2).
               10  WS-R04-F010  PIC X(2).
               10  WS-R04-F011  PIC 9(4).
           05  WS-R04-G02.
               10  WS-R04-F012  PIC X(8).
               10  WS-R04-F013  PIC X(1).
               10  WS-R04-F014  PIC X(4).
               10  WS-R04-F015  PIC X(12).
               10  WS-R04-F016  PIC X(10).
               10  WS-R04-F017  PIC 9(10).
           05  WS-R04-G03.
               10  WS-R04-F018  PIC X(2).
               10  WS-R04-F019  PIC X(1).
               10  WS-R04-F020  PIC X(20).
               10  WS-R04-F021  PIC X(1).
               10  WS-R04-F022  PIC 9(2).
               10  WS-R04-F023  PIC X(8).
           05  WS-R04-G04.
               10  WS-R04-F024  PIC X(1).
               10  WS-R04-F025  PIC X(4).
               10  WS-R04-F026  PIC X(10).
               10  WS-R04-F027  PIC X(20).
               10  WS-R04-F028  PIC 9(10).
               10  WS-R04-F029  PIC 9(2).
           05  WS-R04-G05.
               10  WS-R04-F030  PIC X(20).
               10  WS-R04-F031  PIC X(8).
               10  WS-R04-F032  PIC X(20).
               10  WS-R04-F033  PIC X(1).
               10  WS-R04-F034  PIC X(10).
               10  WS-R04-F035  PIC X(10).
       01  WS-REC-05.
           05  WS-R05-G00.
               10  WS-R05-F000  PIC 9(12).
               10  WS-R05-F001  PIC X(10).
               10  WS-R05-F002  PIC X(8).
               10  WS-R05-F003  PIC X(2).
               10  WS-R05-F004  PIC X(4).
               10  WS-R05-F005  PIC X(2).
           05  WS-R05-G01.
               10  WS-R05-F006  PIC X(2).
               10  WS-R05-F007  PIC X(8).
               10  WS-R05-F008  PIC X(1).
               10  WS-R05-F009  PIC 9(8).
               10  WS-R05-F010  PIC X(12).
               10  WS-R05-F011  PIC X(1).
           05  WS-R05-G02.
               10  WS-R05-F012  PIC X(2).
               10  WS-R05-F013  PIC X(12).
               10  WS-R05-F014  PIC 9(2).
               10  WS-R05-F015  PIC X(2).
               10  WS-R05-F016  PIC X(2).
               10  WS-R05-F017  PIC X(1).
           05  WS-R05-G03.
               10  WS-R05-F018  PIC 9(8).
               10  WS-R05-F019  PIC X(12).
               10  WS-R05-F020  PIC X(2).
               10  WS-R05-F021  PIC X(10).
               10  WS-R05-F022  PIC 9(8).
               10  WS-R05-F023  PIC 9(4).
           05  WS-R05-G04.
               10  WS-R05-F024  PIC 9(4).
               10  WS-R05-F025  PIC X(10).
               10  WS-R05-F026  PIC 9(12).
               10  WS-R05-F027  PIC X(4).
               10  WS-R05-F028  PIC X(4).
               10  WS-R05-F029  PIC 9(1).
           05  WS-R05-G05.
               10  WS-R05-F030  PIC X(20).
               10  WS-R05-F031  PIC 9(1).
               10  WS-R05-F032  PIC 9(4).
               10  WS-R05-F033  PIC X(20).
               10  WS-R05-F034  PIC X(20).
               10  WS-R05-F035  PIC X(8).
       01  WS-REC-06.
           05  WS-R06-G00.
               10  WS-R06-F000  PIC X(12).
               10  WS-R06-F001  PIC X(4).
               10  WS-R06-F002  PIC X(10).
               10  WS-R06-F003  PIC X(10).
               10  WS-R06-F004  PIC 9(4).
               10  WS-R06-F005  PIC X(1).
           05  WS-R06-G01.
               10  WS-R06-F006  PIC X(2).
               10  WS-R06-F007  PIC 9(1).
               10  WS-R06-F008  PIC X(1).
               10  WS-R06-F009  PIC X(20).
               10  WS-R06-F010  PIC X(10).
               10  WS-R06-F011  PIC 9(1).
           05  WS-R06-G02.
               10  WS-R06-F012  PIC X(1).
               10  WS-R06-F013  PIC X(4).
               10  WS-R06-F014  PIC X(8).
               10  WS-R06-F015  PIC X(4).
               10  WS-R06-F016  PIC X(1).
               10  WS-R06-F017  PIC X(2).
           05  WS-R06-G03.
               10  WS-R06-F018  PIC 9(2).
               10  WS-R06-F019  PIC 9(2).
               10  WS-R06-F020  PIC X(4).
               10  WS-R06-F021  PIC X(10).
               10  WS-R06-F022  PIC X(4).
               10  WS-R06-F023  PIC 9(12).
           05  WS-R06-G04.
               10  WS-R06-F024  PIC X(4).
               10  WS-R06-F025  PIC 9(4).
               10  WS-R06-F026  PIC X(1).
               10  WS-R06-F027  PIC X(10).
               10  WS-R06-F028  PIC X(10).
               10  WS-R06-F029  PIC 9(8).
           05  WS-R06-G05.
               10  WS-R06-F030  PIC X(20).
               10  WS-R06-F031  PIC X(12).
               10  WS-R06-F032  PIC X(20).
               10  WS-R06-F033  PIC X(10).
               10  WS-R06-F034  PIC X(2).
               10  WS-R06-F035  PIC 9(4).
       01  WS-RDF-06 REDEFINES WS-REC-06.
           05  WS-RDF-06-HEAD PIC X(40).
           05  WS-RDF-06-MID  PIC X(60).
           05  WS-RDF-06-TAIL PIC X(20).
       01  WS-REC-07.
           05  WS-R07-G00.
               10  WS-R07-F000  PIC X(12).
               10  WS-R07-F001  PIC X(2).
               10  WS-R07-F002  PIC X(4).
               10  WS-R07-F003  PIC X(20).
               10  WS-R07-F004  PIC X(1).
               10  WS-R07-F005  PIC X(4).
           05  WS-R07-G01.
               10  WS-R07-F006  PIC 9(1).
               10  WS-R07-F007  PIC X(20).
               10  WS-R07-F008  PIC X(10).
               10  WS-R07-F009  PIC X(4).
               10  WS-R07-F010  PIC 9(12).
               10  WS-R07-F011  PIC 9(8).
           05  WS-R07-G02.
               10  WS-R07-F012  PIC X(4).
               10  WS-R07-F013  PIC X(4).
               10  WS-R07-F014  PIC X(4).
               10  WS-R07-F015  PIC X(10).
               10  WS-R07-F016  PIC X(1).
               10  WS-R07-F017  PIC 9(4).
           05  WS-R07-G03.
               10  WS-R07-F018  PIC 9(2).
               10  WS-R07-F019  PIC 9(8).
               10  WS-R07-F020  PIC X(4).
               10  WS-R07-F021  PIC 9(2).
               10  WS-R07-F022  PIC X(20).
               10  WS-R07-F023  PIC X(4).
           05  WS-R07-G04.
               10  WS-R07-F024  PIC X(2).
               10  WS-R07-F025  PIC X(1).
               10  WS-R07-F026  PIC X(4).
               10  WS-R07-F027  PIC 9(2).
               10  WS-R07-F028  PIC X(10).
               10  WS-R07-F029  PIC X(2).
           05  WS-R07-G05.
               10  WS-R07-F030  PIC X(12).
               10  WS-R07-F031  PIC X(10).
               10  WS-R07-F032  PIC X(4).
               10  WS-R07-F033  PIC 9(8).
               10  WS-R07-F034  PIC X(12).
               10  WS-R07-F035  PIC 9(2).
       01  WS-REC-08.
           05  WS-R08-G00.
               10  WS-R08-F000  PIC X(20).
               10  WS-R08-F001  PIC X(10).
               10  WS-R08-F002  PIC X(12).
               10  WS-R08-F003  PIC 9(10).
               10  WS-R08-F004  PIC X(10).
               10  WS-R08-F005  PIC X(10).
           05  WS-R08-G01.
               10  WS-R08-F006  PIC X(20).
               10  WS-R08-F007  PIC X(12).
               10  WS-R08-F008  PIC X(12).
               10  WS-R08-F009  PIC X(12).
               10  WS-R08-F010  PIC 9(1).
               10  WS-R08-F011  PIC X(2).
           05  WS-R08-G02.
               10  WS-R08-F012  PIC X(1).
               10  WS-R08-F013  PIC X(8).
               10  WS-R08-F014  PIC 9(12).
               10  WS-R08-F015  PIC X(10).
               10  WS-R08-F016  PIC 9(8).
               10  WS-R08-F017  PIC X(8).
           05  WS-R08-G03.
               10  WS-R08-F018  PIC X(12).
               10  WS-R08-F019  PIC 9(10).
               10  WS-R08-F020  PIC 9(10).
               10  WS-R08-F021  PIC X(12).
               10  WS-R08-F022  PIC X(20).
               10  WS-R08-F023  PIC 9(4).
           05  WS-R08-G04.
               10  WS-R08-F024  PIC X(20).
               10  WS-R08-F025  PIC X(12).
               10  WS-R08-F026  PIC X(8).
               10  WS-R08-F027  PIC 9(8).
               10  WS-R08-F028  PIC 9(12).
               10  WS-R08-F029  PIC X(1).
           05  WS-R08-G05.
               10  WS-R08-F030  PIC 9(12).
               10  WS-R08-F031  PIC 9(10).
               10  WS-R08-F032  PIC X(4).
               10  WS-R08-F033  PIC X(12).
               10  WS-R08-F034  PIC 9(10).
               10  WS-R08-F035  PIC 9(8).
       01  WS-REC-09.
           05  WS-R09-G00.
               10  WS-R09-F000  PIC X(4).
               10  WS-R09-F001  PIC X(1).
               10  WS-R09-F002  PIC X(12).
               10  WS-R09-F003  PIC X(12).
               10  WS-R09-F004  PIC X(8).
               10  WS-R09-F005  PIC X(20).
           05  WS-R09-G01.
               10  WS-R09-F006  PIC 9(10).
               10  WS-R09-F007  PIC X(1).
               10  WS-R09-F008  PIC 9(1).
               10  WS-R09-F009  PIC X(1).
               10  WS-R09-F010  PIC X(8).
               10  WS-R09-F011  PIC 9(8).
           05  WS-R09-G02.
               10  WS-R09-F012  PIC 9(2).
               10  WS-R09-F013  PIC 9(1).
               10  WS-R09-F014  PIC 9(10).
               10  WS-R09-F015  PIC 9(4).
               10  WS-R09-F016  PIC X(20).
               10  WS-R09-F017  PIC X(4).
           05  WS-R09-G03.
               10  WS-R09-F018  PIC X(12).
               10  WS-R09-F019  PIC X(8).
               10  WS-R09-F020  PIC X(8).
               10  WS-R09-F021  PIC 9(2).
               10  WS-R09-F022  PIC X(8).
               10  WS-R09-F023  PIC X(8).
           05  WS-R09-G04.
               10  WS-R09-F024  PIC X(2).
               10  WS-R09-F025  PIC X(8).
               10  WS-R09-F026  PIC X(20).
               10  WS-R09-F027  PIC X(4).
               10  WS-R09-F028  PIC X(20).
               10  WS-R09-F029  PIC X(2).
           05  WS-R09-G05.
               10  WS-R09-F030  PIC 9(12).
               10  WS-R09-F031  PIC 9(4).
               10  WS-R09-F032  PIC X(8).
               10  WS-R09-F033  PIC 9(10).
               10  WS-R09-F034  PIC X(8).
               10  WS-R09-F035  PIC X(20).
       01  WS-RDF-09 REDEFINES WS-REC-09.
           05  WS-RDF-09-HEAD PIC X(40).
           05  WS-RDF-09-MID  PIC X(60).
           05  WS-RDF-09-TAIL PIC X(20).
       01  WS-REC-10.
           05  WS-R10-G00.
               10  WS-R10-F000  PIC 9(1).
               10  WS-R10-F001  PIC 9(12).
               10  WS-R10-F002  PIC 9(2).
               10  WS-R10-F003  PIC X(4).
               10  WS-R10-F004  PIC 9(4).
               10  WS-R10-F005  PIC X(4).
           05  WS-R10-G01.
               10  WS-R10-F006  PIC X(8).
               10  WS-R10-F007  PIC X(20).
               10  WS-R10-F008  PIC X(8).
               10  WS-R10-F009  PIC X(10).
               10  WS-R10-F010  PIC 9(12).
               10  WS-R10-F011  PIC X(12).
           05  WS-R10-G02.
               10  WS-R10-F012  PIC X(10).
               10  WS-R10-F013  PIC X(12).
               10  WS-R10-F014  PIC 9(8).
               10  WS-R10-F015  PIC 9(10).
               10  WS-R10-F016  PIC X(8).
               10  WS-R10-F017  PIC 9(4).
           05  WS-R10-G03.
               10  WS-R10-F018  PIC X(12).
               10  WS-R10-F019  PIC 9(12).
               10  WS-R10-F020  PIC 9(12).
               10  WS-R10-F021  PIC X(8).
               10  WS-R10-F022  PIC 9(8).
               10  WS-R10-F023  PIC 9(12).
           05  WS-R10-G04.
               10  WS-R10-F024  PIC X(2).
               10  WS-R10-F025  PIC X(20).
               10  WS-R10-F026  PIC X(2).
               10  WS-R10-F027  PIC X(4).
               10  WS-R10-F028  PIC X(8).
               10  WS-R10-F029  PIC 9(10).
           05  WS-R10-G05.
               10  WS-R10-F030  PIC 9(1).
               10  WS-R10-F031  PIC 9(10).
               10  WS-R10-F032  PIC X(2).
               10  WS-R10-F033  PIC X(20).
               10  WS-R10-F034  PIC X(1).
               10  WS-R10-F035  PIC X(8).
       01  WS-REC-11.
           05  WS-R11-G00.
               10  WS-R11-F000  PIC X(12).
               10  WS-R11-F001  PIC 9(8).
               10  WS-R11-F002  PIC X(20).
               10  WS-R11-F003  PIC X(4).
               10  WS-R11-F004  PIC 9(4).
               10  WS-R11-F005  PIC X(10).
           05  WS-R11-G01.
               10  WS-R11-F006  PIC X(20).
               10  WS-R11-F007  PIC 9(2).
               10  WS-R11-F008  PIC X(2).
               10  WS-R11-F009  PIC X(12).
               10  WS-R11-F010  PIC X(4).
               10  WS-R11-F011  PIC X(20).
           05  WS-R11-G02.
               10  WS-R11-F012  PIC 9(2).
               10  WS-R11-F013  PIC X(12).
               10  WS-R11-F014  PIC X(20).
               10  WS-R11-F015  PIC X(10).
               10  WS-R11-F016  PIC X(1).
               10  WS-R11-F017  PIC X(20).
           05  WS-R11-G03.
               10  WS-R11-F018  PIC X(8).
               10  WS-R11-F019  PIC X(2).
               10  WS-R11-F020  PIC 9(2).
               10  WS-R11-F021  PIC X(10).
               10  WS-R11-F022  PIC X(1).
               10  WS-R11-F023  PIC X(12).
           05  WS-R11-G04.
               10  WS-R11-F024  PIC X(20).
               10  WS-R11-F025  PIC 9(8).
               10  WS-R11-F026  PIC X(20).
               10  WS-R11-F027  PIC X(20).
               10  WS-R11-F028  PIC X(10).
               10  WS-R11-F029  PIC X(12).
           05  WS-R11-G05.
               10  WS-R11-F030  PIC X(2).
               10  WS-R11-F031  PIC X(10).
               10  WS-R11-F032  PIC X(12).
               10  WS-R11-F033  PIC 9(1).
               10  WS-R11-F034  PIC X(10).
               10  WS-R11-F035  PIC X(2).
       01  WS-REC-12.
           05  WS-R12-G00.
               10  WS-R12-F000  PIC X(2).
               10  WS-R12-F001  PIC 9(1).
               10  WS-R12-F002  PIC X(4).
               10  WS-R12-F003  PIC X(4).
               10  WS-R12-F004  PIC X(12).
               10  WS-R12-F005  PIC X(2).
           05  WS-R12-G01.
               10  WS-R12-F006  PIC X(2).
               10  WS-R12-F007  PIC X(1).
               10  WS-R12-F008  PIC X(12).
               10  WS-R12-F009  PIC 9(1).
               10  WS-R12-F010  PIC X(8).
               10  WS-R12-F011  PIC X(12).
           05  WS-R12-G02.
               10  WS-R12-F012  PIC 9(4).
               10  WS-R12-F013  PIC X(8).
               10  WS-R12-F014  PIC X(2).
               10  WS-R12-F015  PIC X(12).
               10  WS-R12-F016  PIC X(8).
               10  WS-R12-F017  PIC 9(8).
           05  WS-R12-G03.
               10  WS-R12-F018  PIC X(20).
               10  WS-R12-F019  PIC X(20).
               10  WS-R12-F020  PIC X(2).
               10  WS-R12-F021  PIC X(2).
               10  WS-R12-F022  PIC X(20).
               10  WS-R12-F023  PIC 9(8).
           05  WS-R12-G04.
               10  WS-R12-F024  PIC X(20).
               10  WS-R12-F025  PIC X(1).
               10  WS-R12-F026  PIC X(8).
               10  WS-R12-F027  PIC X(2).
               10  WS-R12-F028  PIC 9(12).
               10  WS-R12-F029  PIC 9(10).
           05  WS-R12-G05.
               10  WS-R12-F030  PIC 9(8).
               10  WS-R12-F031  PIC X(1).
               10  WS-R12-F032  PIC X(2).
               10  WS-R12-F033  PIC 9(12).
               10  WS-R12-F034  PIC X(8).
               10  WS-R12-F035  PIC X(12).
       01  WS-RDF-12 REDEFINES WS-REC-12.
           05  WS-RDF-12-HEAD PIC X(40).
           05  WS-RDF-12-MID  PIC X(60).
           05  WS-RDF-12-TAIL PIC X(20).
       01  WS-REC-13.
           05  WS-R13-G00.
               10  WS-R13-F000  PIC 9(12).
               10  WS-R13-F001  PIC X(1).
               10  WS-R13-F002  PIC 9(4).
               10  WS-R13-F003  PIC X(12).
               10  WS-R13-F004  PIC X(12).
               10  WS-R13-F005  PIC X(4).
           05  WS-R13-G01.
               10  WS-R13-F006  PIC X(8).
               10  WS-R13-F007  PIC X(4).
               10  WS-R13-F008  PIC 9(1).
               10  WS-R13-F009  PIC 9(4).
               10  WS-R13-F010  PIC X(8).
               10  WS-R13-F011  PIC X(1).
           05  WS-R13-G02.
               10  WS-R13-F012  PIC X(20).
               10  WS-R13-F013  PIC X(4).
               10  WS-R13-F014  PIC X(4).
               10  WS-R13-F015  PIC 9(8).
               10  WS-R13-F016  PIC X(12).
               10  WS-R13-F017  PIC X(4).
           05  WS-R13-G03.
               10  WS-R13-F018  PIC 9(8).
               10  WS-R13-F019  PIC X(4).
               10  WS-R13-F020  PIC 9(8).
               10  WS-R13-F021  PIC 9(8).
               10  WS-R13-F022  PIC X(12).
               10  WS-R13-F023  PIC X(1).
           05  WS-R13-G04.
               10  WS-R13-F024  PIC 9(8).
               10  WS-R13-F025  PIC 9(1).
               10  WS-R13-F026  PIC 9(12).
               10  WS-R13-F027  PIC X(10).
               10  WS-R13-F028  PIC X(4).
               10  WS-R13-F029  PIC 9(10).
           05  WS-R13-G05.
               10  WS-R13-F030  PIC X(12).
               10  WS-R13-F031  PIC X(4).
               10  WS-R13-F032  PIC 9(4).
               10  WS-R13-F033  PIC X(20).
               10  WS-R13-F034  PIC X(20).
               10  WS-R13-F035  PIC 9(1).
       01  WS-REC-14.
           05  WS-R14-G00.
               10  WS-R14-F000  PIC 9(2).
               10  WS-R14-F001  PIC X(12).
               10  WS-R14-F002  PIC X(20).
               10  WS-R14-F003  PIC X(4).
               10  WS-R14-F004  PIC X(20).
               10  WS-R14-F005  PIC 9(8).
           05  WS-R14-G01.
               10  WS-R14-F006  PIC X(20).
               10  WS-R14-F007  PIC X(4).
               10  WS-R14-F008  PIC X(20).
               10  WS-R14-F009  PIC X(2).
               10  WS-R14-F010  PIC X(4).
               10  WS-R14-F011  PIC X(20).
           05  WS-R14-G02.
               10  WS-R14-F012  PIC X(1).
               10  WS-R14-F013  PIC X(8).
               10  WS-R14-F014  PIC X(2).
               10  WS-R14-F015  PIC 9(12).
               10  WS-R14-F016  PIC X(10).
               10  WS-R14-F017  PIC X(2).
           05  WS-R14-G03.
               10  WS-R14-F018  PIC X(1).
               10  WS-R14-F019  PIC X(4).
               10  WS-R14-F020  PIC 9(2).
               10  WS-R14-F021  PIC X(8).
               10  WS-R14-F022  PIC 9(8).
               10  WS-R14-F023  PIC X(2).
           05  WS-R14-G04.
               10  WS-R14-F024  PIC X(10).
               10  WS-R14-F025  PIC X(2).
               10  WS-R14-F026  PIC X(20).
               10  WS-R14-F027  PIC X(20).
               10  WS-R14-F028  PIC X(20).
               10  WS-R14-F029  PIC X(4).
           05  WS-R14-G05.
               10  WS-R14-F030  PIC 9(4).
               10  WS-R14-F031  PIC 9(4).
               10  WS-R14-F032  PIC 9(2).
               10  WS-R14-F033  PIC 9(2).
               10  WS-R14-F034  PIC 9(10).
               10  WS-R14-F035  PIC X(1).
       01  WS-REC-15.
           05  WS-R15-G00.
               10  WS-R15-F000  PIC X(2).
               10  WS-R15-F001  PIC X(2).
               10  WS-R15-F002  PIC X(1).
               10  WS-R15-F003  PIC 9(1).
               10  WS-R15-F004  PIC X(8).
               10  WS-R15-F005  PIC X(2).
           05  WS-R15-G01.
               10  WS-R15-F006  PIC 9(4).
               10  WS-R15-F007  PIC 9(4).
               10  WS-R15-F008  PIC 9(1).
               10  WS-R15-F009  PIC X(20).
               10  WS-R15-F010  PIC X(1).
               10  WS-R15-F011  PIC X(20).
           05  WS-R15-G02.
               10  WS-R15-F012  PIC 9(10).
               10  WS-R15-F013  PIC X(20).
               10  WS-R15-F014  PIC 9(1).
               10  WS-R15-F015  PIC X(10).
               10  WS-R15-F016  PIC 9(4).
               10  WS-R15-F017  PIC X(4).
           05  WS-R15-G03.
               10  WS-R15-F018  PIC 9(1).
               10  WS-R15-F019  PIC 9(4).
               10  WS-R15-F020  PIC X(12).
               10  WS-R15-F021  PIC X(2).
               10  WS-R15-F022  PIC X(20).
               10  WS-R15-F023  PIC X(12).
           05  WS-R15-G04.
               10  WS-R15-F024  PIC X(10).
               10  WS-R15-F025  PIC 9(2).
               10  WS-R15-F026  PIC X(8).
               10  WS-R15-F027  PIC X(1).
               10  WS-R15-F028  PIC X(20).
               10  WS-R15-F029  PIC 9(10).
           05  WS-R15-G05.
               10  WS-R15-F030  PIC 9(10).
               10  WS-R15-F031  PIC X(2).
               10  WS-R15-F032  PIC X(4).
               10  WS-R15-F033  PIC X(4).
               10  WS-R15-F034  PIC X(8).
               10  WS-R15-F035  PIC X(4).
       01  WS-RDF-15 REDEFINES WS-REC-15.
           05  WS-RDF-15-HEAD PIC X(40).
           05  WS-RDF-15-MID  PIC X(60).
           05  WS-RDF-15-TAIL PIC X(20).
       01  WS-REC-16.
           05  WS-R16-G00.
               10  WS-R16-F000  PIC X(4).
               10  WS-R16-F001  PIC X(1).
               10  WS-R16-F002  PIC X(20).
               10  WS-R16-F003  PIC X(2).
               10  WS-R16-F004  PIC 9(8).
               10  WS-R16-F005  PIC X(1).
           05  WS-R16-G01.
               10  WS-R16-F006  PIC X(2).
               10  WS-R16-F007  PIC X(20).
               10  WS-R16-F008  PIC X(10).
               10  WS-R16-F009  PIC X(8).
               10  WS-R16-F010  PIC 9(2).
               10  WS-R16-F011  PIC 9(10).
           05  WS-R16-G02.
               10  WS-R16-F012  PIC X(20).
               10  WS-R16-F013  PIC X(1).
               10  WS-R16-F014  PIC X(4).
               10  WS-R16-F015  PIC 9(2).
               10  WS-R16-F016  PIC 9(4).
               10  WS-R16-F017  PIC X(2).
           05  WS-R16-G03.
               10  WS-R16-F018  PIC X(1).
               10  WS-R16-F019  PIC X(20).
               10  WS-R16-F020  PIC X(20).
               10  WS-R16-F021  PIC X(2).
               10  WS-R16-F022  PIC X(1).
               10  WS-R16-F023  PIC X(8).
           05  WS-R16-G04.
               10  WS-R16-F024  PIC X(10).
               10  WS-R16-F025  PIC 9(8).
               10  WS-R16-F026  PIC X(12).
               10  WS-R16-F027  PIC X(20).
               10  WS-R16-F028  PIC X(12).
               10  WS-R16-F029  PIC X(2).
           05  WS-R16-G05.
               10  WS-R16-F030  PIC X(10).
               10  WS-R16-F031  PIC X(20).
               10  WS-R16-F032  PIC 9(10).
               10  WS-R16-F033  PIC X(8).
               10  WS-R16-F034  PIC X(2).
               10  WS-R16-F035  PIC 9(1).
       01  WS-REC-17.
           05  WS-R17-G00.
               10  WS-R17-F000  PIC X(12).
               10  WS-R17-F001  PIC 9(2).
               10  WS-R17-F002  PIC X(10).
               10  WS-R17-F003  PIC 9(12).
               10  WS-R17-F004  PIC X(20).
               10  WS-R17-F005  PIC X(8).
           05  WS-R17-G01.
               10  WS-R17-F006  PIC X(10).
               10  WS-R17-F007  PIC X(20).
               10  WS-R17-F008  PIC X(8).
               10  WS-R17-F009  PIC X(2).
               10  WS-R17-F010  PIC X(12).
               10  WS-R17-F011  PIC X(10).
           05  WS-R17-G02.
               10  WS-R17-F012  PIC 9(1).
               10  WS-R17-F013  PIC X(8).
               10  WS-R17-F014  PIC X(8).
               10  WS-R17-F015  PIC X(20).
               10  WS-R17-F016  PIC X(20).
               10  WS-R17-F017  PIC X(8).
           05  WS-R17-G03.
               10  WS-R17-F018  PIC 9(1).
               10  WS-R17-F019  PIC X(8).
               10  WS-R17-F020  PIC X(20).
               10  WS-R17-F021  PIC X(10).
               10  WS-R17-F022  PIC X(1).
               10  WS-R17-F023  PIC X(1).
           05  WS-R17-G04.
               10  WS-R17-F024  PIC X(4).
               10  WS-R17-F025  PIC 9(10).
               10  WS-R17-F026  PIC X(20).
               10  WS-R17-F027  PIC X(8).
               10  WS-R17-F028  PIC X(20).
               10  WS-R17-F029  PIC X(20).
           05  WS-R17-G05.
               10  WS-R17-F030  PIC X(10).
               10  WS-R17-F031  PIC X(20).
               10  WS-R17-F032  PIC X(2).
               10  WS-R17-F033  PIC 9(8).
               10  WS-R17-F034  PIC X(20).
               10  WS-R17-F035  PIC X(2).
       01  WS-REC-18.
           05  WS-R18-G00.
               10  WS-R18-F000  PIC X(12).
               10  WS-R18-F001  PIC X(1).
               10  WS-R18-F002  PIC X(10).
               10  WS-R18-F003  PIC X(2).
               10  WS-R18-F004  PIC 9(10).
               10  WS-R18-F005  PIC X(20).
           05  WS-R18-G01.
               10  WS-R18-F006  PIC X(4).
               10  WS-R18-F007  PIC 9(8).
               10  WS-R18-F008  PIC X(4).
               10  WS-R18-F009  PIC X(2).
               10  WS-R18-F010  PIC 9(1).
               10  WS-R18-F011  PIC 9(8).
           05  WS-R18-G02.
               10  WS-R18-F012  PIC X(4).
               10  WS-R18-F013  PIC 9(8).
               10  WS-R18-F014  PIC X(20).
               10  WS-R18-F015  PIC X(20).
               10  WS-R18-F016  PIC X(12).
               10  WS-R18-F017  PIC X(20).
           05  WS-R18-G03.
               10  WS-R18-F018  PIC X(10).
               10  WS-R18-F019  PIC 9(1).
               10  WS-R18-F020  PIC X(10).
               10  WS-R18-F021  PIC X(8).
               10  WS-R18-F022  PIC 9(4).
               10  WS-R18-F023  PIC X(4).
           05  WS-R18-G04.
               10  WS-R18-F024  PIC X(4).
               10  WS-R18-F025  PIC X(1).
               10  WS-R18-F026  PIC X(2).
               10  WS-R18-F027  PIC 9(1).
               10  WS-R18-F028  PIC 9(10).
               10  WS-R18-F029  PIC X(12).
           05  WS-R18-G05.
               10  WS-R18-F030  PIC X(20).
               10  WS-R18-F031  PIC X(12).
               10  WS-R18-F032  PIC 9(12).
               10  WS-R18-F033  PIC 9(1).
               10  WS-R18-F034  PIC X(4).
               10  WS-R18-F035  PIC X(8).
       01  WS-RDF-18 REDEFINES WS-REC-18.
           05  WS-RDF-18-HEAD PIC X(40).
           05  WS-RDF-18-MID  PIC X(60).
           05  WS-RDF-18-TAIL PIC X(20).
       01  WS-REC-19.
           05  WS-R19-G00.
               10  WS-R19-F000  PIC X(4).
               10  WS-R19-F001  PIC X(2).
               10  WS-R19-F002  PIC X(10).
               10  WS-R19-F003  PIC 9(1).
               10  WS-R19-F004  PIC X(10).
               10  WS-R19-F005  PIC X(1).
           05  WS-R19-G01.
               10  WS-R19-F006  PIC 9(10).
               10  WS-R19-F007  PIC X(10).
               10  WS-R19-F008  PIC 9(2).
               10  WS-R19-F009  PIC X(10).
               10  WS-R19-F010  PIC 9(2).
               10  WS-R19-F011  PIC X(20).
           05  WS-R19-G02.
               10  WS-R19-F012  PIC X(2).
               10  WS-R19-F013  PIC X(1).
               10  WS-R19-F014  PIC X(20).
               10  WS-R19-F015  PIC X(4).
               10  WS-R19-F016  PIC X(4).
               10  WS-R19-F017  PIC X(1).
           05  WS-R19-G03.
               10  WS-R19-F018  PIC X(10).
               10  WS-R19-F019  PIC X(10).
               10  WS-R19-F020  PIC X(8).
               10  WS-R19-F021  PIC X(10).
               10  WS-R19-F022  PIC 9(2).
               10  WS-R19-F023  PIC 9(1).
           05  WS-R19-G04.
               10  WS-R19-F024  PIC 9(10).
               10  WS-R19-F025  PIC 9(2).
               10  WS-R19-F026  PIC X(1).
               10  WS-R19-F027  PIC 9(1).
               10  WS-R19-F028  PIC X(10).
               10  WS-R19-F029  PIC 9(2).
           05  WS-R19-G05.
               10  WS-R19-F030  PIC X(2).
               10  WS-R19-F031  PIC X(12).
               10  WS-R19-F032  PIC X(12).
               10  WS-R19-F033  PIC 9(10).
               10  WS-R19-F034  PIC 9(4).
               10  WS-R19-F035  PIC 9(12).
       01  WS-REC-20.
           05  WS-R20-G00.
               10  WS-R20-F000  PIC X(12).
               10  WS-R20-F001  PIC X(12).
               10  WS-R20-F002  PIC X(8).
               10  WS-R20-F003  PIC X(12).
               10  WS-R20-F004  PIC X(1).
               10  WS-R20-F005  PIC 9(8).
           05  WS-R20-G01.
               10  WS-R20-F006  PIC 9(1).
               10  WS-R20-F007  PIC 9(12).
               10  WS-R20-F008  PIC X(4).
               10  WS-R20-F009  PIC X(12).
               10  WS-R20-F010  PIC X(4).
               10  WS-R20-F011  PIC X(4).
           05  WS-R20-G02.
               10  WS-R20-F012  PIC X(12).
               10  WS-R20-F013  PIC X(20).
               10  WS-R20-F014  PIC 9(4).
               10  WS-R20-F015  PIC 9(2).
               10  WS-R20-F016  PIC 9(10).
               10  WS-R20-F017  PIC X(4).
           05  WS-R20-G03.
               10  WS-R20-F018  PIC X(20).
               10  WS-R20-F019  PIC X(2).
               10  WS-R20-F020  PIC 9(4).
               10  WS-R20-F021  PIC X(8).
               10  WS-R20-F022  PIC X(2).
               10  WS-R20-F023  PIC X(20).
           05  WS-R20-G04.
               10  WS-R20-F024  PIC X(12).
               10  WS-R20-F025  PIC X(20).
               10  WS-R20-F026  PIC X(8).
               10  WS-R20-F027  PIC X(10).
               10  WS-R20-F028  PIC X(20).
               10  WS-R20-F029  PIC 9(12).
           05  WS-R20-G05.
               10  WS-R20-F030  PIC X(4).
               10  WS-R20-F031  PIC X(8).
               10  WS-R20-F032  PIC X(1).
               10  WS-R20-F033  PIC 9(2).
               10  WS-R20-F034  PIC 9(1).
               10  WS-R20-F035  PIC X(10).
       01  WS-REC-21.
           05  WS-R21-G00.
               10  WS-R21-F000  PIC X(4).
               10  WS-R21-F001  PIC 9(12).
               10  WS-R21-F002  PIC 9(1).
               10  WS-R21-F003  PIC X(12).
               10  WS-R21-F004  PIC 9(12).
               10  WS-R21-F005  PIC 9(1).
           05  WS-R21-G01.
               10  WS-R21-F006  PIC X(10).
               10  WS-R21-F007  PIC X(2).
               10  WS-R21-F008  PIC X(20).
               10  WS-R21-F009  PIC 9(12).
               10  WS-R21-F010  PIC X(20).
               10  WS-R21-F011  PIC X(12).
           05  WS-R21-G02.
               10  WS-R21-F012  PIC 9(1).
               10  WS-R21-F013  PIC 9(2).
               10  WS-R21-F014  PIC X(1).
               10  WS-R21-F015  PIC X(20).
               10  WS-R21-F016  PIC X(1).
               10  WS-R21-F017  PIC X(12).
           05  WS-R21-G03.
               10  WS-R21-F018  PIC 9(8).
               10  WS-R21-F019  PIC X(1).
               10  WS-R21-F020  PIC 9(12).
               10  WS-R21-F021  PIC X(4).
               10  WS-R21-F022  PIC 9(4).
               10  WS-R21-F023  PIC X(4).
           05  WS-R21-G04.
               10  WS-R21-F024  PIC X(1).
               10  WS-R21-F025  PIC X(4).
               10  WS-R21-F026  PIC X(20).
               10  WS-R21-F027  PIC X(10).
               10  WS-R21-F028  PIC X(4).
               10  WS-R21-F029  PIC X(1).
           05  WS-R21-G05.
               10  WS-R21-F030  PIC X(1).
               10  WS-R21-F031  PIC X(20).
               10  WS-R21-F032  PIC X(8).
               10  WS-R21-F033  PIC X(10).
               10  WS-R21-F034  PIC X(12).
               10  WS-R21-F035  PIC X(1).
       01  WS-RDF-21 REDEFINES WS-REC-21.
           05  WS-RDF-21-HEAD PIC X(40).
           05  WS-RDF-21-MID  PIC X(60).
           05  WS-RDF-21-TAIL PIC X(20).
       01  WS-REC-22.
           05  WS-R22-G00.
               10  WS-R22-F000  PIC 9(4).
               10  WS-R22-F001  PIC X(1).
               10  WS-R22-F002  PIC X(4).
               10  WS-R22-F003  PIC 9(1).
               10  WS-R22-F004  PIC 9(8).
               10  WS-R22-F005  PIC X(12).
           05  WS-R22-G01.
               10  WS-R22-F006  PIC X(2).
               10  WS-R22-F007  PIC X(10).
               10  WS-R22-F008  PIC X(20).
               10  WS-R22-F009  PIC X(10).
               10  WS-R22-F010  PIC X(4).
               10  WS-R22-F011  PIC 9(12).
           05  WS-R22-G02.
               10  WS-R22-F012  PIC 9(2).
               10  WS-R22-F013  PIC X(12).
               10  WS-R22-F014  PIC X(8).
               10  WS-R22-F015  PIC X(12).
               10  WS-R22-F016  PIC X(1).
               10  WS-R22-F017  PIC 9(4).
           05  WS-R22-G03.
               10  WS-R22-F018  PIC X(8).
               10  WS-R22-F019  PIC 9(12).
               10  WS-R22-F020  PIC 9(12).
               10  WS-R22-F021  PIC X(2).
               10  WS-R22-F022  PIC X(8).
               10  WS-R22-F023  PIC 9(10).
           05  WS-R22-G04.
               10  WS-R22-F024  PIC 9(12).
               10  WS-R22-F025  PIC 9(8).
               10  WS-R22-F026  PIC X(10).
               10  WS-R22-F027  PIC X(20).
               10  WS-R22-F028  PIC X(1).
               10  WS-R22-F029  PIC X(4).
           05  WS-R22-G05.
               10  WS-R22-F030  PIC X(20).
               10  WS-R22-F031  PIC X(12).
               10  WS-R22-F032  PIC 9(4).
               10  WS-R22-F033  PIC X(8).
               10  WS-R22-F034  PIC X(4).
               10  WS-R22-F035  PIC X(2).
       01  WS-REC-23.
           05  WS-R23-G00.
               10  WS-R23-F000  PIC X(12).
               10  WS-R23-F001  PIC X(2).
               10  WS-R23-F002  PIC X(4).
               10  WS-R23-F003  PIC X(12).
               10  WS-R23-F004  PIC 9(10).
               10  WS-R23-F005  PIC X(2).
           05  WS-R23-G01.
               10  WS-R23-F006  PIC X(12).
               10  WS-R23-F007  PIC X(10).
               10  WS-R23-F008  PIC X(2).
               10  WS-R23-F009  PIC 9(2).
               10  WS-R23-F010  PIC X(12).
               10  WS-R23-F011  PIC X(2).
           05  WS-R23-G02.
               10  WS-R23-F012  PIC 9(1).
               10  WS-R23-F013  PIC X(2).
               10  WS-R23-F014  PIC X(20).
               10  WS-R23-F015  PIC X(4).
               10  WS-R23-F016  PIC 9(2).
               10  WS-R23-F017  PIC 9(1).
           05  WS-R23-G03.
               10  WS-R23-F018  PIC X(8).
               10  WS-R23-F019  PIC X(1).
               10  WS-R23-F020  PIC X(20).
               10  WS-R23-F021  PIC X(2).
               10  WS-R23-F022  PIC 9(12).
               10  WS-R23-F023  PIC 9(1).
           05  WS-R23-G04.
               10  WS-R23-F024  PIC X(10).
               10  WS-R23-F025  PIC X(1).
               10  WS-R23-F026  PIC X(20).
               10  WS-R23-F027  PIC X(10).
               10  WS-R23-F028  PIC X(12).
               10  WS-R23-F029  PIC X(2).
           05  WS-R23-G05.
               10  WS-R23-F030  PIC X(12).
               10  WS-R23-F031  PIC X(20).
               10  WS-R23-F032  PIC X(10).
               10  WS-R23-F033  PIC 9(12).
               10  WS-R23-F034  PIC X(1).
               10  WS-R23-F035  PIC 9(4).
       01  WS-REC-24.
           05  WS-R24-G00.
               10  WS-R24-F000  PIC 9(12).
               10  WS-R24-F001  PIC 9(8).
               10  WS-R24-F002  PIC X(8).
               10  WS-R24-F003  PIC 9(12).
               10  WS-R24-F004  PIC X(20).
               10  WS-R24-F005  PIC 9(8).
           05  WS-R24-G01.
               10  WS-R24-F006  PIC X(20).
               10  WS-R24-F007  PIC X(12).
               10  WS-R24-F008  PIC X(20).
               10  WS-R24-F009  PIC X(12).
               10  WS-R24-F010  PIC X(1).
               10  WS-R24-F011  PIC X(8).
           05  WS-R24-G02.
               10  WS-R24-F012  PIC 9(1).
               10  WS-R24-F013  PIC 9(10).
               10  WS-R24-F014  PIC X(12).
               10  WS-R24-F015  PIC X(2).
               10  WS-R24-F016  PIC X(1).
               10  WS-R24-F017  PIC X(8).
           05  WS-R24-G03.
               10  WS-R24-F018  PIC X(12).
               10  WS-R24-F019  PIC X(1).
               10  WS-R24-F020  PIC X(20).
               10  WS-R24-F021  PIC X(4).
               10  WS-R24-F022  PIC 9(8).
               10  WS-R24-F023  PIC 9(12).
           05  WS-R24-G04.
               10  WS-R24-F024  PIC X(10).
               10  WS-R24-F025  PIC X(1).
               10  WS-R24-F026  PIC X(10).
               10  WS-R24-F027  PIC 9(1).
               10  WS-R24-F028  PIC X(8).
               10  WS-R24-F029  PIC 9(1).
           05  WS-R24-G05.
               10  WS-R24-F030  PIC X(8).
               10  WS-R24-F031  PIC X(12).
               10  WS-R24-F032  PIC 9(4).
               10  WS-R24-F033  PIC X(4).
               10  WS-R24-F034  PIC X(10).
               10  WS-R24-F035  PIC X(20).
       01  WS-RDF-24 REDEFINES WS-REC-24.
           05  WS-RDF-24-HEAD PIC X(40).
           05  WS-RDF-24-MID  PIC X(60).
           05  WS-RDF-24-TAIL PIC X(20).
       01  WS-REC-25.
           05  WS-R25-G00.
               10  WS-R25-F000  PIC 9(8).
               10  WS-R25-F001  PIC X(2).
               10  WS-R25-F002  PIC X(1).
               10  WS-R25-F003  PIC 9(12).
               10  WS-R25-F004  PIC X(12).
               10  WS-R25-F005  PIC X(2).
           05  WS-R25-G01.
               10  WS-R25-F006  PIC X(2).
               10  WS-R25-F007  PIC X(12).
               10  WS-R25-F008  PIC X(20).
               10  WS-R25-F009  PIC X(8).
               10  WS-R25-F010  PIC X(20).
               10  WS-R25-F011  PIC X(2).
           05  WS-R25-G02.
               10  WS-R25-F012  PIC X(8).
               10  WS-R25-F013  PIC X(20).
               10  WS-R25-F014  PIC X(12).
               10  WS-R25-F015  PIC X(4).
               10  WS-R25-F016  PIC 9(12).
               10  WS-R25-F017  PIC X(1).
           05  WS-R25-G03.
               10  WS-R25-F018  PIC X(20).
               10  WS-R25-F019  PIC X(2).
               10  WS-R25-F020  PIC X(4).
               10  WS-R25-F021  PIC X(8).
               10  WS-R25-F022  PIC X(1).
               10  WS-R25-F023  PIC 9(4).
           05  WS-R25-G04.
               10  WS-R25-F024  PIC X(4).
               10  WS-R25-F025  PIC 9(1).
               10  WS-R25-F026  PIC X(10).
               10  WS-R25-F027  PIC X(20).
               10  WS-R25-F028  PIC X(10).
               10  WS-R25-F029  PIC X(12).
           05  WS-R25-G05.
               10  WS-R25-F030  PIC 9(12).
               10  WS-R25-F031  PIC X(1).
               10  WS-R25-F032  PIC X(4).
               10  WS-R25-F033  PIC 9(10).
               10  WS-R25-F034  PIC 9(2).
               10  WS-R25-F035  PIC X(8).
       01  WS-REC-26.
           05  WS-R26-G00.
               10  WS-R26-F000  PIC 9(2).
               10  WS-R26-F001  PIC X(8).
               10  WS-R26-F002  PIC X(2).
               10  WS-R26-F003  PIC X(12).
               10  WS-R26-F004  PIC X(20).
               10  WS-R26-F005  PIC X(10).
           05  WS-R26-G01.
               10  WS-R26-F006  PIC X(20).
               10  WS-R26-F007  PIC X(8).
               10  WS-R26-F008  PIC 9(10).
               10  WS-R26-F009  PIC X(20).
               10  WS-R26-F010  PIC X(1).
               10  WS-R26-F011  PIC X(4).
           05  WS-R26-G02.
               10  WS-R26-F012  PIC X(20).
               10  WS-R26-F013  PIC X(8).
               10  WS-R26-F014  PIC X(8).
               10  WS-R26-F015  PIC X(2).
               10  WS-R26-F016  PIC X(2).
               10  WS-R26-F017  PIC X(10).
           05  WS-R26-G03.
               10  WS-R26-F018  PIC 9(12).
               10  WS-R26-F019  PIC X(20).
               10  WS-R26-F020  PIC X(12).
               10  WS-R26-F021  PIC 9(12).
               10  WS-R26-F022  PIC X(8).
               10  WS-R26-F023  PIC X(8).
           05  WS-R26-G04.
               10  WS-R26-F024  PIC 9(12).
               10  WS-R26-F025  PIC X(12).
               10  WS-R26-F026  PIC 9(12).
               10  WS-R26-F027  PIC 9(10).
               10  WS-R26-F028  PIC X(12).
               10  WS-R26-F029  PIC X(4).
           05  WS-R26-G05.
               10  WS-R26-F030  PIC X(1).
               10  WS-R26-F031  PIC X(8).
               10  WS-R26-F032  PIC 9(2).
               10  WS-R26-F033  PIC X(12).
               10  WS-R26-F034  PIC X(2).
               10  WS-R26-F035  PIC X(20).
       01  WS-REC-27.
           05  WS-R27-G00.
               10  WS-R27-F000  PIC X(4).
               10  WS-R27-F001  PIC X(10).
               10  WS-R27-F002  PIC 9(2).
               10  WS-R27-F003  PIC X(4).
               10  WS-R27-F004  PIC 9(10).
               10  WS-R27-F005  PIC 9(4).
           05  WS-R27-G01.
               10  WS-R27-F006  PIC X(20).
               10  WS-R27-F007  PIC X(4).
               10  WS-R27-F008  PIC X(4).
               10  WS-R27-F009  PIC X(4).
               10  WS-R27-F010  PIC X(12).
               10  WS-R27-F011  PIC X(1).
           05  WS-R27-G02.
               10  WS-R27-F012  PIC X(4).
               10  WS-R27-F013  PIC X(2).
               10  WS-R27-F014  PIC 9(12).
               10  WS-R27-F015  PIC X(1).
               10  WS-R27-F016  PIC X(10).
               10  WS-R27-F017  PIC X(10).
           05  WS-R27-G03.
               10  WS-R27-F018  PIC X(8).
               10  WS-R27-F019  PIC 9(1).
               10  WS-R27-F020  PIC X(20).
               10  WS-R27-F021  PIC X(10).
               10  WS-R27-F022  PIC X(1).
               10  WS-R27-F023  PIC X(10).
           05  WS-R27-G04.
               10  WS-R27-F024  PIC 9(10).
               10  WS-R27-F025  PIC X(12).
               10  WS-R27-F026  PIC X(10).
               10  WS-R27-F027  PIC 9(1).
               10  WS-R27-F028  PIC X(12).
               10  WS-R27-F029  PIC X(12).
           05  WS-R27-G05.
               10  WS-R27-F030  PIC X(1).
               10  WS-R27-F031  PIC X(20).
               10  WS-R27-F032  PIC X(20).
               10  WS-R27-F033  PIC 9(12).
               10  WS-R27-F034  PIC X(20).
               10  WS-R27-F035  PIC X(20).
       01  WS-RDF-27 REDEFINES WS-REC-27.
           05  WS-RDF-27-HEAD PIC X(40).
           05  WS-RDF-27-MID  PIC X(60).
           05  WS-RDF-27-TAIL PIC X(20).
       01  WS-REC-28.
           05  WS-R28-G00.
               10  WS-R28-F000  PIC 9(12).
               10  WS-R28-F001  PIC 9(4).
               10  WS-R28-F002  PIC X(1).
               10  WS-R28-F003  PIC X(8).
               10  WS-R28-F004  PIC X(10).
               10  WS-R28-F005  PIC X(1).
           05  WS-R28-G01.
               10  WS-R28-F006  PIC 9(10).
               10  WS-R28-F007  PIC X(1).
               10  WS-R28-F008  PIC X(8).
               10  WS-R28-F009  PIC X(8).
               10  WS-R28-F010  PIC X(1).
               10  WS-R28-F011  PIC X(10).
           05  WS-R28-G02.
               10  WS-R28-F012  PIC X(12).
               10  WS-R28-F013  PIC X(8).
               10  WS-R28-F014  PIC 9(10).
               10  WS-R28-F015  PIC X(12).
               10  WS-R28-F016  PIC X(2).
               10  WS-R28-F017  PIC 9(8).
           05  WS-R28-G03.
               10  WS-R28-F018  PIC X(12).
               10  WS-R28-F019  PIC X(20).
               10  WS-R28-F020  PIC X(20).
               10  WS-R28-F021  PIC 9(8).
               10  WS-R28-F022  PIC X(12).
               10  WS-R28-F023  PIC X(8).
           05  WS-R28-G04.
               10  WS-R28-F024  PIC X(2).
               10  WS-R28-F025  PIC X(4).
               10  WS-R28-F026  PIC X(12).
               10  WS-R28-F027  PIC X(2).
               10  WS-R28-F028  PIC 9(1).
               10  WS-R28-F029  PIC X(10).
           05  WS-R28-G05.
               10  WS-R28-F030  PIC X(8).
               10  WS-R28-F031  PIC X(4).
               10  WS-R28-F032  PIC X(1).
               10  WS-R28-F033  PIC 9(1).
               10  WS-R28-F034  PIC X(12).
               10  WS-R28-F035  PIC 9(10).
       01  WS-REC-29.
           05  WS-R29-G00.
               10  WS-R29-F000  PIC X(4).
               10  WS-R29-F001  PIC 9(10).
               10  WS-R29-F002  PIC X(20).
               10  WS-R29-F003  PIC 9(10).
               10  WS-R29-F004  PIC X(4).
               10  WS-R29-F005  PIC X(12).
           05  WS-R29-G01.
               10  WS-R29-F006  PIC 9(12).
               10  WS-R29-F007  PIC X(20).
               10  WS-R29-F008  PIC 9(12).
               10  WS-R29-F009  PIC X(20).
               10  WS-R29-F010  PIC X(8).
               10  WS-R29-F011  PIC X(8).
           05  WS-R29-G02.
               10  WS-R29-F012  PIC X(20).
               10  WS-R29-F013  PIC 9(4).
               10  WS-R29-F014  PIC X(1).
               10  WS-R29-F015  PIC X(12).
               10  WS-R29-F016  PIC X(20).
               10  WS-R29-F017  PIC X(20).
           05  WS-R29-G03.
               10  WS-R29-F018  PIC X(1).
               10  WS-R29-F019  PIC X(10).
               10  WS-R29-F020  PIC X(10).
               10  WS-R29-F021  PIC X(2).
               10  WS-R29-F022  PIC X(12).
               10  WS-R29-F023  PIC X(20).
           05  WS-R29-G04.
               10  WS-R29-F024  PIC X(20).
               10  WS-R29-F025  PIC 9(12).
               10  WS-R29-F026  PIC 9(4).
               10  WS-R29-F027  PIC X(2).
               10  WS-R29-F028  PIC X(20).
               10  WS-R29-F029  PIC X(20).
           05  WS-R29-G05.
               10  WS-R29-F030  PIC X(20).
               10  WS-R29-F031  PIC X(20).
               10  WS-R29-F032  PIC 9(2).
               10  WS-R29-F033  PIC X(20).
               10  WS-R29-F034  PIC X(10).
               10  WS-R29-F035  PIC X(8).
       01  WS-REC-30.
           05  WS-R30-G00.
               10  WS-R30-F000  PIC X(1).
               10  WS-R30-F001  PIC X(8).
               10  WS-R30-F002  PIC X(2).
               10  WS-R30-F003  PIC X(12).
               10  WS-R30-F004  PIC X(2).
               10  WS-R30-F005  PIC X(1).
           05  WS-R30-G01.
               10  WS-R30-F006  PIC X(8).
               10  WS-R30-F007  PIC X(4).
               10  WS-R30-F008  PIC X(1).
               10  WS-R30-F009  PIC X(8).
               10  WS-R30-F010  PIC X(10).
               10  WS-R30-F011  PIC X(20).
           05  WS-R30-G02.
               10  WS-R30-F012  PIC X(8).
               10  WS-R30-F013  PIC X(4).
               10  WS-R30-F014  PIC X(10).
               10  WS-R30-F015  PIC X(10).
               10  WS-R30-F016  PIC 9(2).
               10  WS-R30-F017  PIC 9(1).
           05  WS-R30-G03.
               10  WS-R30-F018  PIC 9(12).
               10  WS-R30-F019  PIC X(10).
               10  WS-R30-F020  PIC X(8).
               10  WS-R30-F021  PIC X(20).
               10  WS-R30-F022  PIC X(1).
               10  WS-R30-F023  PIC X(8).
           05  WS-R30-G04.
               10  WS-R30-F024  PIC X(1).
               10  WS-R30-F025  PIC X(8).
               10  WS-R30-F026  PIC X(2).
               10  WS-R30-F027  PIC X(1).
               10  WS-R30-F028  PIC X(10).
               10  WS-R30-F029  PIC 9(1).
           05  WS-R30-G05.
               10  WS-R30-F030  PIC X(20).
               10  WS-R30-F031  PIC X(8).
               10  WS-R30-F032  PIC 9(2).
               10  WS-R30-F033  PIC X(20).
               10  WS-R30-F034  PIC X(1).
               10  WS-R30-F035  PIC X(20).
       01  WS-RDF-30 REDEFINES WS-REC-30.
           05  WS-RDF-30-HEAD PIC X(40).
           05  WS-RDF-30-MID  PIC X(60).
           05  WS-RDF-30-TAIL PIC X(20).
       01  WS-REC-31.
           05  WS-R31-G00.
               10  WS-R31-F000  PIC X(10).
               10  WS-R31-F001  PIC X(4).
               10  WS-R31-F002  PIC 9(4).
               10  WS-R31-F003  PIC X(2).
               10  WS-R31-F004  PIC 9(1).
               10  WS-R31-F005  PIC X(10).
           05  WS-R31-G01.
               10  WS-R31-F006  PIC X(12).
               10  WS-R31-F007  PIC X(20).
               10  WS-R31-F008  PIC X(1).
               10  WS-R31-F009  PIC X(12).
               10  WS-R31-F010  PIC X(1).
               10  WS-R31-F011  PIC 9(1).
           05  WS-R31-G02.
               10  WS-R31-F012  PIC 9(10).
               10  WS-R31-F013  PIC X(1).
               10  WS-R31-F014  PIC X(12).
               10  WS-R31-F015  PIC X(2).
               10  WS-R31-F016  PIC X(2).
               10  WS-R31-F017  PIC X(2).
           05  WS-R31-G03.
               10  WS-R31-F018  PIC 9(2).
               10  WS-R31-F019  PIC X(4).
               10  WS-R31-F020  PIC X(1).
               10  WS-R31-F021  PIC X(1).
               10  WS-R31-F022  PIC 9(1).
               10  WS-R31-F023  PIC X(10).
           05  WS-R31-G04.
               10  WS-R31-F024  PIC X(12).
               10  WS-R31-F025  PIC 9(8).
               10  WS-R31-F026  PIC X(2).
               10  WS-R31-F027  PIC X(1).
               10  WS-R31-F028  PIC X(12).
               10  WS-R31-F029  PIC X(10).
           05  WS-R31-G05.
               10  WS-R31-F030  PIC X(20).
               10  WS-R31-F031  PIC X(8).
               10  WS-R31-F032  PIC X(4).
               10  WS-R31-F033  PIC X(4).
               10  WS-R31-F034  PIC X(2).
               10  WS-R31-F035  PIC X(20).
       01  WS-REC-32.
           05  WS-R32-G00.
               10  WS-R32-F000  PIC X(12).
               10  WS-R32-F001  PIC X(8).
               10  WS-R32-F002  PIC X(2).
               10  WS-R32-F003  PIC X(2).
               10  WS-R32-F004  PIC 9(2).
               10  WS-R32-F005  PIC X(10).
           05  WS-R32-G01.
               10  WS-R32-F006  PIC 9(12).
               10  WS-R32-F007  PIC X(8).
               10  WS-R32-F008  PIC X(8).
               10  WS-R32-F009  PIC 9(12).
               10  WS-R32-F010  PIC X(4).
               10  WS-R32-F011  PIC X(2).
           05  WS-R32-G02.
               10  WS-R32-F012  PIC X(12).
               10  WS-R32-F013  PIC 9(4).
               10  WS-R32-F014  PIC 9(1).
               10  WS-R32-F015  PIC X(8).
               10  WS-R32-F016  PIC X(2).
               10  WS-R32-F017  PIC 9(2).
           05  WS-R32-G03.
               10  WS-R32-F018  PIC 9(8).
               10  WS-R32-F019  PIC 9(1).
               10  WS-R32-F020  PIC X(20).
               10  WS-R32-F021  PIC X(20).
               10  WS-R32-F022  PIC 9(8).
               10  WS-R32-F023  PIC X(8).
           05  WS-R32-G04.
               10  WS-R32-F024  PIC 9(1).
               10  WS-R32-F025  PIC 9(10).
               10  WS-R32-F026  PIC X(20).
               10  WS-R32-F027  PIC X(2).
               10  WS-R32-F028  PIC X(20).
               10  WS-R32-F029  PIC X(4).
           05  WS-R32-G05.
               10  WS-R32-F030  PIC X(4).
               10  WS-R32-F031  PIC X(4).
               10  WS-R32-F032  PIC 9(2).
               10  WS-R32-F033  PIC X(4).
               10  WS-R32-F034  PIC 9(2).
               10  WS-R32-F035  PIC X(12).
       01  WS-REC-33.
           05  WS-R33-G00.
               10  WS-R33-F000  PIC X(2).
               10  WS-R33-F001  PIC X(1).
               10  WS-R33-F002  PIC X(10).
               10  WS-R33-F003  PIC X(2).
               10  WS-R33-F004  PIC X(20).
               10  WS-R33-F005  PIC 9(10).
           05  WS-R33-G01.
               10  WS-R33-F006  PIC X(4).
               10  WS-R33-F007  PIC 9(8).
               10  WS-R33-F008  PIC 9(10).
               10  WS-R33-F009  PIC X(20).
               10  WS-R33-F010  PIC X(20).
               10  WS-R33-F011  PIC 9(2).
           05  WS-R33-G02.
               10  WS-R33-F012  PIC X(1).
               10  WS-R33-F013  PIC X(10).
               10  WS-R33-F014  PIC X(20).
               10  WS-R33-F015  PIC 9(2).
               10  WS-R33-F016  PIC X(12).
               10  WS-R33-F017  PIC X(20).
           05  WS-R33-G03.
               10  WS-R33-F018  PIC 9(4).
               10  WS-R33-F019  PIC X(1).
               10  WS-R33-F020  PIC X(10).
               10  WS-R33-F021  PIC X(12).
               10  WS-R33-F022  PIC X(10).
               10  WS-R33-F023  PIC 9(4).
           05  WS-R33-G04.
               10  WS-R33-F024  PIC X(12).
               10  WS-R33-F025  PIC 9(8).
               10  WS-R33-F026  PIC X(8).
               10  WS-R33-F027  PIC 9(8).
               10  WS-R33-F028  PIC 9(12).
               10  WS-R33-F029  PIC X(2).
           05  WS-R33-G05.
               10  WS-R33-F030  PIC 9(4).
               10  WS-R33-F031  PIC X(12).
               10  WS-R33-F032  PIC X(10).
               10  WS-R33-F033  PIC X(4).
               10  WS-R33-F034  PIC X(8).
               10  WS-R33-F035  PIC 9(1).
       01  WS-RDF-33 REDEFINES WS-REC-33.
           05  WS-RDF-33-HEAD PIC X(40).
           05  WS-RDF-33-MID  PIC X(60).
           05  WS-RDF-33-TAIL PIC X(20).
       01  WS-REC-34.
           05  WS-R34-G00.
               10  WS-R34-F000  PIC 9(12).
               10  WS-R34-F001  PIC X(20).
               10  WS-R34-F002  PIC X(4).
               10  WS-R34-F003  PIC X(20).
               10  WS-R34-F004  PIC X(20).
               10  WS-R34-F005  PIC X(4).
           05  WS-R34-G01.
               10  WS-R34-F006  PIC X(12).
               10  WS-R34-F007  PIC 9(10).
               10  WS-R34-F008  PIC X(20).
               10  WS-R34-F009  PIC 9(1).
               10  WS-R34-F010  PIC 9(1).
               10  WS-R34-F011  PIC 9(2).
           05  WS-R34-G02.
               10  WS-R34-F012  PIC 9(4).
               10  WS-R34-F013  PIC X(20).
               10  WS-R34-F014  PIC 9(1).
               10  WS-R34-F015  PIC X(12).
               10  WS-R34-F016  PIC 9(4).
               10  WS-R34-F017  PIC X(10).
           05  WS-R34-G03.
               10  WS-R34-F018  PIC X(8).
               10  WS-R34-F019  PIC X(12).
               10  WS-R34-F020  PIC X(4).
               10  WS-R34-F021  PIC 9(12).
               10  WS-R34-F022  PIC 9(4).
               10  WS-R34-F023  PIC X(8).
           05  WS-R34-G04.
               10  WS-R34-F024  PIC X(20).
               10  WS-R34-F025  PIC 9(1).
               10  WS-R34-F026  PIC X(2).
               10  WS-R34-F027  PIC X(2).
               10  WS-R34-F028  PIC X(2).
               10  WS-R34-F029  PIC X(8).
           05  WS-R34-G05.
               10  WS-R34-F030  PIC X(2).
               10  WS-R34-F031  PIC X(1).
               10  WS-R34-F032  PIC X(8).
               10  WS-R34-F033  PIC X(10).
               10  WS-R34-F034  PIC 9(10).
               10  WS-R34-F035  PIC X(1).
       01  WS-REC-35.
           05  WS-R35-G00.
               10  WS-R35-F000  PIC X(4).
               10  WS-R35-F001  PIC X(20).
               10  WS-R35-F002  PIC X(8).
               10  WS-R35-F003  PIC X(10).
               10  WS-R35-F004  PIC X(4).
               10  WS-R35-F005  PIC X(20).
           05  WS-R35-G01.
               10  WS-R35-F006  PIC X(4).
               10  WS-R35-F007  PIC X(12).
               10  WS-R35-F008  PIC X(2).
               10  WS-R35-F009  PIC X(12).
               10  WS-R35-F010  PIC 9(4).
               10  WS-R35-F011  PIC 9(2).
           05  WS-R35-G02.
               10  WS-R35-F012  PIC 9(8).
               10  WS-R35-F013  PIC 9(12).
               10  WS-R35-F014  PIC X(2).
               10  WS-R35-F015  PIC X(8).
               10  WS-R35-F016  PIC X(8).
               10  WS-R35-F017  PIC X(20).
           05  WS-R35-G03.
               10  WS-R35-F018  PIC 9(1).
               10  WS-R35-F019  PIC X(12).
               10  WS-R35-F020  PIC X(12).
               10  WS-R35-F021  PIC X(12).
               10  WS-R35-F022  PIC X(1).
               10  WS-R35-F023  PIC 9(4).
           05  WS-R35-G04.
               10  WS-R35-F024  PIC X(1).
               10  WS-R35-F025  PIC 9(1).
               10  WS-R35-F026  PIC X(4).
               10  WS-R35-F027  PIC 9(2).
               10  WS-R35-F028  PIC X(10).
               10  WS-R35-F029  PIC X(10).
           05  WS-R35-G05.
               10  WS-R35-F030  PIC X(1).
               10  WS-R35-F031  PIC X(10).
               10  WS-R35-F032  PIC 9(8).
               10  WS-R35-F033  PIC X(2).
               10  WS-R35-F034  PIC X(8).
               10  WS-R35-F035  PIC 9(4).
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
               PERFORM P0041 THRU P0048
               MOVE WS-REC-00 TO WS-TAB-00-TXT(WS-IX-0)
           END-PERFORM
           PERFORM VARYING WS-IX-1 FROM 1 BY 1
                   UNTIL WS-IX-1 > 20
               PERFORM P0273 THRU P0280
               MOVE WS-REC-01 TO WS-TAB-01-TXT(WS-IX-1)
           END-PERFORM
           PERFORM VARYING WS-IX-2 FROM 1 BY 1
                   UNTIL WS-IX-2 > 20
               PERFORM P0145 THRU P0152
               MOVE WS-REC-02 TO WS-TAB-02-TXT(WS-IX-2)
           END-PERFORM
           PERFORM VARYING WS-IX-3 FROM 1 BY 1
                   UNTIL WS-IX-3 > 20
               PERFORM P0233 THRU P0240
               MOVE WS-REC-03 TO WS-TAB-03-TXT(WS-IX-3)
           END-PERFORM
           IF WS-MODE = 'A1'
               PERFORM P0001 THRU P0008
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0009 THRU P0016
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0017 THRU P0024
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0025 THRU P0032
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0033 THRU P0040
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0041 THRU P0048
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0049 THRU P0056
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0057 THRU P0064
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0065 THRU P0072
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0073 THRU P0080
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0081 THRU P0088
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0089 THRU P0096
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0097 THRU P0104
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0105 THRU P0112
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0113 THRU P0120
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0121 THRU P0128
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0129 THRU P0136
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0137 THRU P0144
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0145 THRU P0152
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0153 THRU P0160
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0161 THRU P0168
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0169 THRU P0176
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0177 THRU P0184
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0185 THRU P0192
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0193 THRU P0200
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0201 THRU P0208
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0209 THRU P0216
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0217 THRU P0224
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0225 THRU P0232
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0233 THRU P0240
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0241 THRU P0248
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0249 THRU P0256
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0257 THRU P0264
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0265 THRU P0272
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0273 THRU P0280
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0281 THRU P0288
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0289 THRU P0296
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0297 THRU P0304
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0305 THRU P0312
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0313 THRU P0320
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0321 THRU P0328
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0329 THRU P0336
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0337 THRU P0344
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0345 THRU P0352
           END-IF
           IF WS-MODE = 'A1'
               PERFORM P0353 THRU P0360
           END-IF
           STOP RUN.
       P0001.
           MOVE 'Z' TO WS-R00-F028(13:1)
           MOVE SPACES TO WS-R01-G03
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE 'A' TO WS-R01-F003
           IF WS-R00-F031 = SPACES
               MOVE 'A' TO WS-R01-F014
               COMPUTE WS-IX-2 = WS-IX-2 + 1
           ELSE
               MOVE 'P' TO WS-R01-F005
               MOVE ZERO TO WS-R00-F027
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0008
           END-IF.
       P0002.
           MOVE 'Q' TO WS-R01-F008
           MOVE ZERO TO WS-R00-F007
           IF WS-R01-F030 = ZERO
               MOVE 'Q' TO WS-R00-F013
               MOVE 'N' TO WS-R00-F019
               MOVE 'E' TO WS-R01-F009
           ELSE
               MOVE SPACES TO WS-R01-G04
               MOVE WS-REC-01 TO WS-REC-00
               MOVE WS-R01-F016 TO WS-TAB-11-KEY(WS-IX-2)
               MOVE WS-TAB-09-TXT(WS-IX-1) TO WS-R01-F027
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0008
           END-IF.
       P0003.
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE 'W' TO WS-R01-F021
           MOVE 'Z' TO WS-R01-F009(3:1)
           IF WS-R01-F009 = SPACES
               MOVE 'Z' TO WS-R01-F005(1:1)
               MOVE WS-R01-F020 TO WS-TAB-07-TXT(WS-IX-6)
               MOVE 'N' TO WS-R00-F018
               MOVE 'Z' TO WS-R00-F029(3:1)
           ELSE
               MOVE 'K' TO WS-R00-F031
               MOVE SPACES TO WS-R01-G00
               MOVE WS-REC-01 TO WS-REC-00
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0008
           END-IF.
       P0004.
           MOVE ZERO TO WS-R01-F030
           MOVE WS-R01-F013 TO WS-TAB-11-TXT(WS-IX-6)
           MOVE 'A' TO WS-R01-F021
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'M' TO WS-R01-F028
               MOVE 'Q' TO WS-R00-F019
             WHEN 'B2'
               MOVE WS-R01-F020 TO WS-RDF-00-MID
               MOVE WS-R01-F031 TO WS-TAB-09-KEY(WS-IX-5)
             WHEN 'C3'
               MOVE ZERO TO WS-R00-F009
               MOVE WS-TAB-08-TXT(WS-IX-2) TO WS-R00-F014
               MOVE WS-TAB-08-TXT(WS-IX-6) TO WS-R00-F020
             WHEN OTHER
               MOVE WS-REC-01 TO WS-REC-00
               MOVE WS-REC-00 TO WS-REC-01
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0008
           END-IF.
       P0005.
           MOVE WS-REC-01 TO WS-REC-00
           MOVE WS-TAB-04-TXT(WS-IX-0) TO WS-R01-F002
           MOVE 'Q' TO WS-R00-F003
           MOVE SPACES TO WS-R01-G04.
       P0006.
           MOVE WS-R00-F015 TO WS-RDF-00-MID
           MOVE SPACES TO WS-R00-G00
           MOVE WS-REC-00 TO WS-REC-01
           MOVE WS-TAB-09-KEY(WS-IX-6) TO WS-R00-F007
           IF WS-R01-F005 = SPACES
               MOVE 'B' TO WS-R00-F021
               MOVE 'S' TO WS-R00-F012
           ELSE
               MOVE 'T' TO WS-R01-F021
               MOVE 'H' TO WS-R00-F006
           END-IF.
       P0007.
           MOVE WS-R00-F006 TO WS-TAB-00-KEY(WS-IX-7)
           MOVE WS-REC-00 TO WS-REC-01
           MOVE WS-REC-01 TO WS-REC-00
           MOVE 'P' TO WS-R00-F032
           IF WS-R00-F008 = ZERO
               MOVE 'Z' TO WS-R00-F028(14:1)
               MOVE 'A' TO WS-R01-F026
               MOVE WS-R00-F022 TO WS-TAB-03-KEY(WS-IX-1)
           ELSE
               MOVE WS-REC-01 TO WS-REC-00
               MOVE WS-REC-01 TO WS-REC-00
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0008
           END-IF.
       P0008.
           MOVE 'R' TO WS-R01-F008
           MOVE 'O' TO WS-R00-F024
           IF WS-R01-F000 = SPACES
               MOVE WS-REC-00 TO WS-REC-01
               MOVE WS-R00-F011 TO WS-TAB-03-KEY(WS-IX-2)
               MOVE WS-R01-F023 TO WS-TAB-02-KEY(WS-IX-7)
           ELSE
               MOVE SPACES TO WS-R01-G03
               MOVE 'Z' TO WS-R00-F026(5:1)
               MOVE WS-R01-F021 TO WS-RDF-00-HEAD
           END-IF
           CONTINUE.
       P0009.
           MOVE SPACES TO WS-R02-G04
           COMPUTE WS-IX-5 = WS-IX-5 + 1
           MOVE 'G' TO WS-R02-F029
           MOVE SPACES TO WS-R01-G05
           IF WS-R02-F029 = SPACES
               MOVE WS-R01-F018 TO WS-TAB-06-TXT(WS-IX-0)
               MOVE 'Q' TO WS-R01-F022
               MOVE WS-R01-F024 TO WS-TAB-03-KEY(WS-IX-5)
           ELSE
               MOVE WS-R01-F008 TO WS-TAB-04-TXT(WS-IX-3)
               MOVE ZERO TO WS-R02-F015
               MOVE ZERO TO WS-R02-F015
           END-IF.
       P0010.
           MOVE WS-R01-F035 TO WS-TAB-10-KEY(WS-IX-2)
           MOVE 'Z' TO WS-R02-F008(4:1)
           MOVE WS-REC-02 TO WS-REC-01
           IF WS-R02-F015 = ZERO
               MOVE WS-REC-02 TO WS-REC-01
               MOVE 'W' TO WS-R01-F028
               MOVE 'Z' TO WS-R02-F015(1:1)
               MOVE 'Y' TO WS-R01-F025
           ELSE
               MOVE SPACES TO WS-R01-G04
               MOVE 'S' TO WS-R01-F022
               MOVE WS-TAB-09-TXT(WS-IX-7) TO WS-R02-F030
           END-IF.
       P0011.
           MOVE 'D' TO WS-R01-F000
           MOVE WS-TAB-10-KEY(WS-IX-4) TO WS-R01-F005
           MOVE 'Z' TO WS-R01-F004(11:1)
           MOVE SPACES TO WS-R02-G05
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'I' TO WS-R01-F028
               MOVE 'O' TO WS-R02-F018
               MOVE WS-R01-F006 TO WS-RDF-00-TAIL
             WHEN 'B2'
               MOVE WS-REC-02 TO WS-REC-01
               MOVE WS-REC-02 TO WS-REC-01
               MOVE 'Q' TO WS-R01-F030
             WHEN 'C3'
               MOVE 'G' TO WS-R01-F011
               MOVE 'Z' TO WS-R01-F017(3:1)
               MOVE 'Z' TO WS-R02-F026(16:1)
             WHEN OTHER
               MOVE 'Q' TO WS-R01-F000
               MOVE ZERO TO WS-R01-F017
           END-EVALUATE.
       P0012.
           MOVE 'Z' TO WS-R01-F017(3:1)
           MOVE WS-REC-02 TO WS-REC-01
           MOVE WS-REC-01 TO WS-REC-02
           IF WS-FLAG = 'Y'
               GO TO P0009
           END-IF.
       P0013.
           MOVE WS-REC-01 TO WS-REC-02
           MOVE 'W' TO WS-R01-F014
           MOVE 'F' TO WS-R01-F014
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'R' TO WS-R01-F021
               MOVE WS-REC-01 TO WS-REC-02
               MOVE WS-R02-F006 TO WS-RDF-00-HEAD
             WHEN 'B2'
               MOVE 'Z' TO WS-R02-F005(1:1)
               MOVE 'U' TO WS-R01-F011
               MOVE 'U' TO WS-R01-F032
             WHEN 'C3'
               MOVE WS-REC-01 TO WS-REC-02
               MOVE WS-TAB-02-KEY(WS-IX-4) TO WS-R02-F011
             WHEN OTHER
               MOVE WS-TAB-10-TXT(WS-IX-2) TO WS-R01-F013
               MOVE ZERO TO WS-R01-F023
               MOVE 'Q' TO WS-R02-F009
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0016
           END-IF.
       P0014.
           MOVE 'D' TO WS-R01-F005
           MOVE 'Z' TO WS-R02-F015(1:1)
           MOVE WS-R02-F027 TO WS-RDF-00-MID.
       P0015.
           MOVE WS-REC-01 TO WS-REC-02
           MOVE SPACES TO WS-R02-G00
           MOVE WS-R01-F024 TO WS-RDF-00-MID
           MOVE SPACES TO WS-R02-G00.
       P0016.
           MOVE 'C' TO WS-R02-F000
           MOVE 'Z' TO WS-R02-F029(7:1)
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE 'X' TO WS-R01-F022
           IF WS-R01-F021 = SPACES
               MOVE 'S' TO WS-R02-F008
               MOVE SPACES TO WS-R01-G04
           ELSE
               MOVE 'U' TO WS-R02-F032
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE WS-R02-F006 TO WS-RDF-00-HEAD
           END-IF
           CONTINUE.
       P0017.
           MOVE 'Z' TO WS-R03-F017(3:1)
           MOVE 'Z' TO WS-R02-F017(3:1)
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE WS-TAB-03-KEY(WS-IX-7) TO WS-R02-F010
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'S' TO WS-R02-F030
               MOVE 'D' TO WS-R02-F033
               MOVE ZERO TO WS-R02-F025
             WHEN 'B2'
               MOVE WS-TAB-03-KEY(WS-IX-4) TO WS-R02-F012
               MOVE 'H' TO WS-R03-F026
               MOVE WS-REC-02 TO WS-REC-03
             WHEN 'C3'
               MOVE WS-REC-02 TO WS-REC-03
               MOVE WS-TAB-06-TXT(WS-IX-2) TO WS-R02-F024
               MOVE SPACES TO WS-R02-G03
             WHEN OTHER
               MOVE 'Z' TO WS-R02-F027(8:1)
               MOVE ZERO TO WS-R02-F017
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0024
           END-IF.
       P0018.
           MOVE WS-R02-F014 TO WS-RDF-00-TAIL
           COMPUTE WS-IX-5 = WS-IX-5 + 1
           MOVE SPACES TO WS-R03-G05
           MOVE 'Z' TO WS-R02-F032(4:1)
           IF WS-R02-F030 = SPACES
               MOVE 'B' TO WS-R03-F026
               MOVE WS-TAB-05-TXT(WS-IX-1) TO WS-R03-F009
               MOVE WS-REC-02 TO WS-REC-03
               MOVE 'A' TO WS-R03-F021
           ELSE
               MOVE 'P' TO WS-R02-F002
               MOVE WS-REC-03 TO WS-REC-02
               MOVE SPACES TO WS-R03-G05
               MOVE 'Z' TO WS-R02-F018(2:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0024
           END-IF.
       P0019.
           MOVE WS-R03-F007 TO WS-RDF-00-HEAD
           MOVE WS-R03-F025 TO WS-RDF-03-TAIL
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           IF WS-R02-F009 = ZERO
               MOVE 'Z' TO WS-R03-F014(2:1)
               MOVE WS-R02-F029 TO WS-RDF-03-MID
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'G' TO WS-R03-F031
           ELSE
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE SPACES TO WS-R03-G05
               MOVE 'Z' TO WS-R03-F023(13:1)
           END-IF.
       P0020.
           MOVE WS-REC-03 TO WS-REC-02
           MOVE 'O' TO WS-R02-F031
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           IF WS-FLAG = 'Y'
               GO TO P0024
           END-IF.
       P0021.
           MOVE 'S' TO WS-R03-F009
           MOVE 'Z' TO WS-R02-F017(6:1).
       P0022.
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE 'Q' TO WS-R02-F012.
       P0023.
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           MOVE 'Q' TO WS-R03-F002
           IF WS-FLAG = 'Y'
               GO TO P0024
           END-IF.
       P0024.
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE 'V' TO WS-R03-F007
           MOVE 'Q' TO WS-R03-F025
           CONTINUE.
       P0025.
           MOVE WS-R03-F026 TO WS-RDF-03-HEAD
           MOVE WS-REC-04 TO WS-REC-03
           IF WS-R04-F021 = SPACES
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE SPACES TO WS-R04-G02
               MOVE WS-TAB-08-KEY(WS-IX-5) TO WS-R03-F009
           ELSE
               MOVE ZERO TO WS-R04-F009
               MOVE WS-R04-F018 TO WS-RDF-03-TAIL
           END-IF.
       P0026.
           MOVE WS-TAB-05-TXT(WS-IX-2) TO WS-R03-F035
           MOVE WS-R03-F030 TO WS-TAB-10-KEY(WS-IX-4)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R04-F028
               MOVE 'Q' TO WS-R03-F025
               MOVE 'E' TO WS-R03-F007
             WHEN 'B2'
               MOVE SPACES TO WS-R03-G02
               MOVE WS-REC-04 TO WS-REC-03
               MOVE SPACES TO WS-R04-G05
             WHEN 'C3'
               MOVE 'Q' TO WS-R04-F007
               MOVE SPACES TO WS-R04-G00
               MOVE WS-REC-04 TO WS-REC-03
             WHEN OTHER
               MOVE WS-REC-04 TO WS-REC-03
               MOVE WS-REC-04 TO WS-REC-03
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0025
           END-IF.
       P0027.
           MOVE WS-REC-04 TO WS-REC-03
           MOVE 'V' TO WS-R04-F032
           IF WS-R04-F035 = SPACES
               MOVE WS-REC-04 TO WS-REC-03
               MOVE WS-TAB-10-TXT(WS-IX-4) TO WS-R04-F034
               MOVE 'I' TO WS-R04-F031
               MOVE SPACES TO WS-R03-G04
           ELSE
               MOVE WS-REC-04 TO WS-REC-03
               MOVE WS-R03-F011 TO WS-RDF-03-MID
               MOVE WS-R03-F007 TO WS-RDF-03-HEAD
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0025
           END-IF.
       P0028.
           MOVE 'X' TO WS-R04-F010
           MOVE SPACES TO WS-R03-G05
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-TAB-03-KEY(WS-IX-7) TO WS-R04-F027
               MOVE 'O' TO WS-R04-F013
               MOVE SPACES TO WS-R03-G00
             WHEN 'B2'
               MOVE WS-R04-F008 TO WS-TAB-01-KEY(WS-IX-6)
               MOVE 'V' TO WS-R04-F012
               MOVE 'Z' TO WS-R03-F028(1:1)
             WHEN 'C3'
               MOVE ZERO TO WS-R04-F009
               MOVE SPACES TO WS-R04-G05
               MOVE 'G' TO WS-R04-F027
             WHEN OTHER
               MOVE WS-R03-F017 TO WS-TAB-07-TXT(WS-IX-4)
               MOVE 'H' TO WS-R04-F026
               MOVE SPACES TO WS-R04-G01
           END-EVALUATE.
       P0029.
           MOVE SPACES TO WS-R03-G02
           MOVE 'Z' TO WS-R03-F014(1:1)
           MOVE WS-R04-F002 TO WS-RDF-03-HEAD
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-03 TO WS-REC-04
               MOVE 'Z' TO WS-R03-F011(7:1)
               MOVE 'K' TO WS-R04-F014
             WHEN 'B2'
               MOVE WS-REC-03 TO WS-REC-04
               MOVE SPACES TO WS-R03-G04
             WHEN 'C3'
               MOVE 'Q' TO WS-R03-F002
               MOVE WS-REC-04 TO WS-REC-03
               COMPUTE WS-IX-1 = WS-IX-1 + 1
             WHEN OTHER
               MOVE WS-R03-F022 TO WS-RDF-03-HEAD
               MOVE 'E' TO WS-R04-F033
               MOVE 'Q' TO WS-R04-F033
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0025
           END-IF.
       P0030.
           MOVE WS-TAB-01-KEY(WS-IX-5) TO WS-R03-F027
           MOVE 'A' TO WS-R03-F022
           MOVE 'B' TO WS-R03-F008
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-TAB-05-TXT(WS-IX-4) TO WS-R03-F001
               MOVE 'Q' TO WS-R04-F033
               MOVE 'W' TO WS-R04-F006
             WHEN 'B2'
               MOVE WS-R04-F018 TO WS-RDF-03-MID
               MOVE ZERO TO WS-R04-F017
               MOVE 'M' TO WS-R03-F019
             WHEN 'C3'
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE ZERO TO WS-R04-F028
             WHEN OTHER
               MOVE 'Z' TO WS-R04-F012(2:1)
               MOVE WS-TAB-10-KEY(WS-IX-1) TO WS-R03-F011
               MOVE WS-REC-04 TO WS-REC-03
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0025
           END-IF.
       P0031.
           MOVE WS-REC-04 TO WS-REC-03
           MOVE 'U' TO WS-R03-F030
           MOVE WS-TAB-06-TXT(WS-IX-5) TO WS-R03-F008
           MOVE 'C' TO WS-R04-F005
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-TAB-04-TXT(WS-IX-7) TO WS-R04-F008
               MOVE WS-R04-F010 TO WS-RDF-03-TAIL
               MOVE 'Q' TO WS-R03-F021
             WHEN 'B2'
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE 'N' TO WS-R04-F010
               MOVE SPACES TO WS-R03-G05
             WHEN 'C3'
               MOVE 'Z' TO WS-R04-F030(17:1)
               MOVE 'I' TO WS-R03-F011
               MOVE 'W' TO WS-R04-F021
             WHEN OTHER
               MOVE 'X' TO WS-R04-F025
               MOVE WS-R03-F000 TO WS-TAB-08-KEY(WS-IX-2)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0025
           END-IF.
       P0032.
           MOVE ZERO TO WS-R03-F032
           MOVE WS-REC-03 TO WS-REC-04
           MOVE WS-REC-03 TO WS-REC-04
           IF WS-R04-F033 = SPACES
               MOVE 'O' TO WS-R03-F033
               MOVE WS-REC-04 TO WS-REC-03
               MOVE SPACES TO WS-R04-G02
           ELSE
               MOVE WS-R04-F012 TO WS-TAB-00-TXT(WS-IX-7)
               MOVE WS-R03-F032 TO WS-TAB-06-TXT(WS-IX-6)
               MOVE WS-TAB-02-KEY(WS-IX-3) TO WS-R04-F011
               MOVE 'C' TO WS-R03-F009
           END-IF
           CONTINUE.
       P0033.
           MOVE ZERO TO WS-R05-F031
           MOVE 'D' TO WS-R04-F003
           MOVE ZERO TO WS-R05-F023
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R04-G03
               MOVE ZERO TO WS-R04-F017
               MOVE WS-REC-04 TO WS-REC-05
             WHEN 'B2'
               MOVE 'Z' TO WS-R05-F001(6:1)
               MOVE WS-TAB-07-KEY(WS-IX-1) TO WS-R04-F011
               MOVE WS-REC-04 TO WS-REC-05
             WHEN 'C3'
               MOVE WS-TAB-03-KEY(WS-IX-7) TO WS-R04-F007
               MOVE WS-REC-05 TO WS-REC-04
             WHEN OTHER
               MOVE WS-R05-F005 TO WS-TAB-10-TXT(WS-IX-2)
               MOVE WS-R04-F035 TO WS-RDF-03-TAIL
               MOVE WS-REC-05 TO WS-REC-04
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0040
           END-IF.
       P0034.
           MOVE 'V' TO WS-R05-F017
           MOVE WS-REC-05 TO WS-REC-04
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE WS-R04-F025 TO WS-TAB-04-KEY(WS-IX-4)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R04-F018
               MOVE 'G' TO WS-R05-F007
               MOVE 'Z' TO WS-R05-F035(6:1)
             WHEN 'B2'
               MOVE WS-R05-F016 TO WS-TAB-00-TXT(WS-IX-1)
               MOVE SPACES TO WS-R05-G02
             WHEN 'C3'
               MOVE 'Z' TO WS-R05-F022(4:1)
               MOVE WS-R04-F026 TO WS-RDF-03-HEAD
             WHEN OTHER
               MOVE SPACES TO WS-R04-G00
               MOVE SPACES TO WS-R04-G04
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0033
           END-IF.
       P0035.
           MOVE WS-REC-05 TO WS-REC-04
           MOVE 'Z' TO WS-R05-F001(4:1)
           MOVE WS-REC-04 TO WS-REC-05
           MOVE 'G' TO WS-R04-F012
           IF WS-FLAG = 'Y'
               GO TO P0040
           END-IF.
       P0036.
           MOVE 'Q' TO WS-R05-F020
           MOVE 'Q' TO WS-R04-F019
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           IF WS-R04-F005 = SPACES
               MOVE ZERO TO WS-R04-F029
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'Q' TO WS-R04-F019
           ELSE
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE WS-REC-04 TO WS-REC-05
               MOVE ZERO TO WS-R04-F004
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0033
           END-IF.
       P0037.
           MOVE 'W' TO WS-R05-F033
           MOVE WS-REC-05 TO WS-REC-04
           MOVE WS-R05-F015 TO WS-TAB-06-KEY(WS-IX-5)
           IF WS-R05-F009 = ZERO
               MOVE WS-R05-F026 TO WS-RDF-03-MID
               MOVE 'C' TO WS-R05-F027
           ELSE
               MOVE 'Y' TO WS-R05-F033
               MOVE WS-REC-04 TO WS-REC-05
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0040
           END-IF.
       P0038.
           MOVE ZERO TO WS-R04-F004
           MOVE WS-REC-04 TO WS-REC-05.
       P0039.
           MOVE SPACES TO WS-R05-G03
           MOVE 'F' TO WS-R05-F010
           IF WS-FLAG = 'Y'
               GO TO P0033
           END-IF.
       P0040.
           MOVE 'Z' TO WS-R05-F034(4:1)
           MOVE WS-R05-F023 TO WS-TAB-09-KEY(WS-IX-6)
           MOVE WS-REC-05 TO WS-REC-04
           MOVE ZERO TO WS-R05-F009
           IF WS-R04-F009 = ZERO
               MOVE WS-R04-F011 TO WS-TAB-05-TXT(WS-IX-2)
               MOVE 'Z' TO WS-R05-F025(5:1)
               MOVE SPACES TO WS-R04-G00
               COMPUTE WS-IX-1 = WS-IX-1 + 1
           ELSE
               MOVE 'Z' TO WS-R05-F033(4:1)
               MOVE 'F' TO WS-R04-F031
           END-IF
           CONTINUE.
       P0041.
           MOVE 'Z' TO WS-R05-F032(2:1)
           MOVE WS-R06-F035 TO WS-RDF-06-MID
           MOVE SPACES TO WS-R05-G01
           MOVE WS-R05-F012 TO WS-TAB-08-KEY(WS-IX-3)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R05-F029
               MOVE WS-REC-05 TO WS-REC-06
               MOVE WS-R06-F014 TO WS-TAB-00-KEY(WS-IX-6)
             WHEN 'B2'
               MOVE WS-REC-05 TO WS-REC-06
               MOVE WS-R05-F012 TO WS-TAB-01-KEY(WS-IX-5)
               MOVE WS-TAB-02-KEY(WS-IX-4) TO WS-R06-F007
             WHEN 'C3'
               MOVE WS-TAB-00-KEY(WS-IX-1) TO WS-R05-F031
               MOVE 'Z' TO WS-R05-F019(6:1)
               MOVE WS-TAB-03-TXT(WS-IX-3) TO WS-R05-F028
             WHEN OTHER
               MOVE WS-R06-F027 TO WS-RDF-06-HEAD
               MOVE 'Y' TO WS-R05-F008
           END-EVALUATE.
       P0042.
           MOVE SPACES TO WS-R05-G02
           MOVE WS-TAB-01-TXT(WS-IX-5) TO WS-R05-F020
           IF WS-R06-F027 = SPACES
               MOVE WS-R06-F023 TO WS-RDF-03-TAIL
               MOVE WS-TAB-10-TXT(WS-IX-2) TO WS-R06-F019
               MOVE WS-R06-F032 TO WS-TAB-08-KEY(WS-IX-4)
               MOVE WS-TAB-04-KEY(WS-IX-3) TO WS-R05-F030
           ELSE
               MOVE 'S' TO WS-R06-F027
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE 'Z' TO WS-R06-F014
               MOVE 'Q' TO WS-R06-F007
           END-IF.
       P0043.
           MOVE WS-R06-F007 TO WS-RDF-03-TAIL
           MOVE 'Q' TO WS-R06-F018
           MOVE WS-TAB-00-KEY(WS-IX-4) TO WS-R06-F026
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R05-F018
               MOVE 'C' TO WS-R05-F027
               MOVE ZERO TO WS-R06-F023
             WHEN 'B2'
               MOVE SPACES TO WS-R06-G03
               MOVE 'Z' TO WS-R05-F030(4:1)
               MOVE SPACES TO WS-R05-G03
             WHEN 'C3'
               MOVE 'E' TO WS-R06-F006
               MOVE 'L' TO WS-R05-F028
             WHEN OTHER
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE ZERO TO WS-R06-F004
               MOVE WS-R06-F014 TO WS-RDF-03-HEAD
           END-EVALUATE.
       P0044.
           MOVE 'Z' TO WS-R05-F032(2:1)
           MOVE 'Q' TO WS-R06-F034
           MOVE WS-TAB-08-TXT(WS-IX-6) TO WS-R05-F017
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'L' TO WS-R06-F001
               MOVE 'Q' TO WS-R06-F012
               MOVE WS-TAB-00-TXT(WS-IX-7) TO WS-R06-F027
             WHEN 'B2'
               MOVE WS-REC-05 TO WS-REC-06
               MOVE ZERO TO WS-R06-F029
             WHEN 'C3'
               MOVE WS-R05-F004 TO WS-TAB-11-TXT(WS-IX-7)
               MOVE WS-REC-06 TO WS-REC-05
             WHEN OTHER
               MOVE 'Z' TO WS-R06-F029(1:1)
               MOVE WS-R05-F035 TO WS-RDF-03-TAIL
           END-EVALUATE.
       P0045.
           MOVE 'A' TO WS-R06-F033
           MOVE 'U' TO WS-R06-F016.
       P0046.
           MOVE 'Z' TO WS-R06-F010(5:1)
           MOVE 'B' TO WS-R06-F027
           MOVE WS-R05-F025 TO WS-TAB-05-KEY(WS-IX-2)
           IF WS-R06-F030 = SPACES
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE WS-R05-F023 TO WS-RDF-06-TAIL
               MOVE 'G' TO WS-R06-F024
           ELSE
               MOVE 'M' TO WS-R06-F020
               MOVE WS-REC-06 TO WS-REC-05
               MOVE 'Z' TO WS-R06-F013
               MOVE WS-R05-F026 TO WS-RDF-06-HEAD
           END-IF.
       P0047.
           MOVE 'Y' TO WS-R05-F020
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE SPACES TO WS-R06-G05
           MOVE 'Q' TO WS-R06-F016
           IF WS-R05-F009 = ZERO
               MOVE 'Z' TO WS-R06-F014(5:1)
               MOVE WS-TAB-10-TXT(WS-IX-1) TO WS-R05-F033
               MOVE WS-REC-06 TO WS-REC-05
           ELSE
               MOVE WS-R05-F008 TO WS-RDF-06-HEAD
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE WS-R05-F014 TO WS-TAB-10-TXT(WS-IX-6)
               MOVE SPACES TO WS-R05-G03
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0048
           END-IF.
       P0048.
           MOVE WS-R06-F027 TO WS-TAB-06-TXT(WS-IX-6)
           MOVE SPACES TO WS-R05-G04
           MOVE WS-R05-F017 TO WS-TAB-06-KEY(WS-IX-4)
           MOVE WS-REC-06 TO WS-REC-05
           IF WS-R06-F028 = SPACES
               MOVE 'Q' TO WS-R06-F019
               MOVE 'Z' TO WS-R05-F035
               MOVE WS-TAB-02-KEY(WS-IX-2) TO WS-R05-F028
               COMPUTE WS-IX-0 = WS-IX-0 + 1
           ELSE
               MOVE WS-R05-F016 TO WS-RDF-06-MID
               MOVE 'Z' TO WS-R06-F013(2:1)
               MOVE 'Z' TO WS-R06-F029(3:1)
               MOVE WS-REC-06 TO WS-REC-05
           END-IF
           CONTINUE.
       P0049.
           MOVE 'Z' TO WS-R06-F010(6:1)
           MOVE WS-REC-06 TO WS-REC-07
           MOVE WS-TAB-05-TXT(WS-IX-3) TO WS-R06-F000
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-07 TO WS-REC-06
               MOVE WS-REC-07 TO WS-REC-06
               MOVE 'K' TO WS-R07-F007
             WHEN 'B2'
               MOVE WS-R06-F028 TO WS-TAB-09-KEY(WS-IX-0)
               MOVE ZERO TO WS-R07-F011
               MOVE WS-REC-07 TO WS-REC-06
             WHEN 'C3'
               MOVE WS-REC-07 TO WS-REC-06
               MOVE ZERO TO WS-R06-F007
               MOVE WS-TAB-08-KEY(WS-IX-5) TO WS-R06-F032
             WHEN OTHER
               MOVE WS-REC-07 TO WS-REC-06
               MOVE WS-REC-06 TO WS-REC-07
               MOVE WS-TAB-01-KEY(WS-IX-0) TO WS-R07-F020
           END-EVALUATE.
       P0050.
           MOVE WS-R06-F008 TO WS-TAB-11-TXT(WS-IX-0)
           MOVE WS-REC-07 TO WS-REC-06
           MOVE 'Q' TO WS-R07-F004
           MOVE WS-R06-F005 TO WS-RDF-06-HEAD
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE WS-TAB-05-TXT(WS-IX-1) TO WS-R06-F019
               MOVE WS-REC-07 TO WS-REC-06
             WHEN 'B2'
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE WS-R07-F029 TO WS-TAB-08-TXT(WS-IX-4)
               MOVE 'G' TO WS-R06-F002
             WHEN 'C3'
               MOVE 'N' TO WS-R07-F030
               MOVE WS-R06-F020 TO WS-TAB-11-TXT(WS-IX-6)
               MOVE WS-REC-06 TO WS-REC-07
             WHEN OTHER
               MOVE SPACES TO WS-R06-G02
               MOVE ZERO TO WS-R07-F035
           END-EVALUATE.
       P0051.
           MOVE WS-TAB-03-KEY(WS-IX-0) TO WS-R06-F031
           MOVE 'D' TO WS-R06-F013
           MOVE WS-REC-06 TO WS-REC-07
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R07-F020(1:1)
               MOVE 'Q' TO WS-R06-F006
               COMPUTE WS-IX-2 = WS-IX-2 + 1
             WHEN 'B2'
               MOVE ZERO TO WS-R06-F018
               MOVE WS-REC-07 TO WS-REC-06
               MOVE WS-REC-06 TO WS-REC-07
             WHEN 'C3'
               MOVE WS-REC-06 TO WS-REC-07
               MOVE WS-REC-06 TO WS-REC-07
             WHEN OTHER
               MOVE WS-R06-F005 TO WS-RDF-06-TAIL
               MOVE WS-R06-F005 TO WS-RDF-06-MID
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0049
           END-IF.
       P0052.
           MOVE WS-TAB-11-KEY(WS-IX-1) TO WS-R06-F023
           MOVE SPACES TO WS-R07-G00.
       P0053.
           MOVE WS-REC-06 TO WS-REC-07
           MOVE 'Z' TO WS-R07-F032(1:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'V' TO WS-R07-F014
               MOVE WS-REC-06 TO WS-REC-07
               MOVE SPACES TO WS-R07-G01
             WHEN 'B2'
               MOVE WS-R07-F030 TO WS-RDF-06-TAIL
               MOVE 'C' TO WS-R06-F012
               MOVE WS-R07-F011 TO WS-TAB-01-TXT(WS-IX-1)
             WHEN 'C3'
               MOVE SPACES TO WS-R07-G01
               MOVE WS-REC-06 TO WS-REC-07
               MOVE WS-REC-06 TO WS-REC-07
             WHEN OTHER
               MOVE WS-R06-F010 TO WS-RDF-06-TAIL
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE 'Z' TO WS-R06-F003(3:1)
           END-EVALUATE.
       P0054.
           MOVE WS-R07-F001 TO WS-TAB-00-TXT(WS-IX-2)
           MOVE SPACES TO WS-R07-G02
           MOVE WS-REC-07 TO WS-REC-06
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R07-F024
               MOVE WS-R06-F031 TO WS-TAB-05-KEY(WS-IX-4)
               MOVE WS-REC-06 TO WS-REC-07
             WHEN 'B2'
               MOVE WS-R06-F010 TO WS-TAB-03-KEY(WS-IX-5)
               MOVE WS-R07-F007 TO WS-TAB-05-TXT(WS-IX-6)
             WHEN 'C3'
               MOVE WS-R07-F031 TO WS-RDF-06-HEAD
               MOVE WS-REC-06 TO WS-REC-07
             WHEN OTHER
               MOVE 'Q' TO WS-R06-F011
               MOVE 'Z' TO WS-R06-F027(5:1)
               MOVE WS-TAB-00-KEY(WS-IX-4) TO WS-R07-F019
           END-EVALUATE.
       P0055.
           MOVE WS-R06-F031 TO WS-RDF-06-MID
           MOVE 'C' TO WS-R06-F003
           MOVE 'Q' TO WS-R06-F026
           MOVE 'Q' TO WS-R06-F018
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'C' TO WS-R06-F009
               MOVE WS-R06-F009 TO WS-TAB-08-TXT(WS-IX-0)
               MOVE 'Q' TO WS-R07-F027
             WHEN 'B2'
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE SPACES TO WS-R06-G02
               MOVE 'W' TO WS-R07-F016
             WHEN 'C3'
               MOVE 'A' TO WS-R06-F026
               MOVE 'D' TO WS-R06-F028
               MOVE WS-TAB-05-KEY(WS-IX-5) TO WS-R06-F035
             WHEN OTHER
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE WS-R06-F033 TO WS-TAB-10-KEY(WS-IX-4)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0056
           END-IF.
       P0056.
           MOVE ZERO TO WS-R06-F011
           MOVE WS-REC-06 TO WS-REC-07
           IF WS-R07-F001 = SPACES
               MOVE WS-R07-F033 TO WS-RDF-06-MID
               MOVE WS-R06-F032 TO WS-TAB-02-TXT(WS-IX-5)
           ELSE
               MOVE 'Z' TO WS-R06-F031(3:1)
               MOVE 'Y' TO WS-R07-F012
               MOVE WS-REC-06 TO WS-REC-07
               MOVE WS-TAB-05-TXT(WS-IX-3) TO WS-R07-F024
           END-IF
           CONTINUE.
       P0057.
           MOVE WS-REC-08 TO WS-REC-07
           MOVE 'P' TO WS-R07-F003
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R08-F026(1:1)
               MOVE 'P' TO WS-R08-F026
             WHEN 'B2'
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE 'G' TO WS-R07-F015
             WHEN 'C3'
               MOVE ZERO TO WS-R08-F020
               MOVE ZERO TO WS-R08-F035
             WHEN OTHER
               MOVE WS-REC-07 TO WS-REC-08
               MOVE WS-TAB-09-KEY(WS-IX-6) TO WS-R07-F014
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0064
           END-IF.
       P0058.
           MOVE ZERO TO WS-R07-F027
           MOVE WS-REC-08 TO WS-REC-07
           IF WS-FLAG = 'Y'
               GO TO P0064
           END-IF.
       P0059.
           MOVE WS-R07-F012 TO WS-TAB-10-KEY(WS-IX-5)
           MOVE WS-R08-F024 TO WS-TAB-01-TXT(WS-IX-1)
           IF WS-R08-F029 = SPACES
               MOVE WS-TAB-00-KEY(WS-IX-7) TO WS-R07-F004
               MOVE 'Z' TO WS-R07-F017(2:1)
               MOVE SPACES TO WS-R08-G05
               MOVE WS-REC-08 TO WS-REC-07
           ELSE
               MOVE 'X' TO WS-R08-F022
               MOVE WS-REC-07 TO WS-REC-08
               MOVE ZERO TO WS-R07-F017
               MOVE WS-R07-F025 TO WS-TAB-04-KEY(WS-IX-5)
           END-IF.
       P0060.
           MOVE 'H' TO WS-R08-F025
           MOVE WS-REC-08 TO WS-REC-07
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R08-G01
               MOVE 'I' TO WS-R08-F022
             WHEN 'B2'
               MOVE WS-R08-F016 TO WS-RDF-06-HEAD
               MOVE SPACES TO WS-R08-G05
             WHEN 'C3'
               MOVE WS-REC-08 TO WS-REC-07
               MOVE 'E' TO WS-R07-F000
               MOVE 'P' TO WS-R08-F022
             WHEN OTHER
               MOVE 'I' TO WS-R07-F015
               MOVE WS-R08-F030 TO WS-RDF-06-HEAD
               MOVE SPACES TO WS-R08-G00
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0064
           END-IF.
       P0061.
           MOVE ZERO TO WS-R08-F016
           MOVE 'E' TO WS-R07-F028.
       P0062.
           MOVE WS-REC-07 TO WS-REC-08
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           IF WS-FLAG = 'Y'
               GO TO P0057
           END-IF.
       P0063.
           MOVE 'S' TO WS-R08-F029
           MOVE WS-REC-07 TO WS-REC-08
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'S' TO WS-R07-F032
               MOVE 'U' TO WS-R07-F032
             WHEN 'B2'
               MOVE ZERO TO WS-R08-F031
               MOVE 'W' TO WS-R07-F009
             WHEN 'C3'
               MOVE WS-REC-08 TO WS-REC-07
               MOVE 'Q' TO WS-R07-F001
               MOVE 'V' TO WS-R08-F007
             WHEN OTHER
               MOVE WS-R08-F033 TO WS-RDF-06-HEAD
               MOVE ZERO TO WS-R07-F017
           END-EVALUATE.
       P0064.
           MOVE ZERO TO WS-R08-F010
           MOVE ZERO TO WS-R08-F027
           IF WS-R08-F010 = ZERO
               MOVE 'Z' TO WS-R07-F034(2:1)
               MOVE WS-REC-07 TO WS-REC-08
           ELSE
               MOVE 'P' TO WS-R07-F009
               MOVE 'L' TO WS-R08-F033
               MOVE ZERO TO WS-R08-F019
               MOVE 'W' TO WS-R08-F025
           END-IF
           CONTINUE.
       P0065.
           MOVE 'Z' TO WS-R08-F020(7:1)
           MOVE 'R' TO WS-R09-F001
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-09 TO WS-REC-08
               MOVE 'Z' TO WS-R08-F020(2:1)
               MOVE 'Z' TO WS-R08-F005(4:1)
             WHEN 'B2'
               MOVE WS-REC-08 TO WS-REC-09
               MOVE WS-R08-F000 TO WS-TAB-01-KEY(WS-IX-3)
               MOVE ZERO TO WS-R08-F030
             WHEN 'C3'
               MOVE WS-R09-F006 TO WS-RDF-06-MID
               MOVE WS-REC-09 TO WS-REC-08
             WHEN OTHER
               MOVE 'I' TO WS-R09-F025
               MOVE ZERO TO WS-R08-F010
               MOVE 'C' TO WS-R08-F033
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0072
           END-IF.
       P0066.
           MOVE SPACES TO WS-R09-G02
           MOVE WS-REC-08 TO WS-REC-09
           MOVE WS-TAB-11-TXT(WS-IX-6) TO WS-R09-F013
           IF WS-R08-F029 = SPACES
               MOVE WS-TAB-01-KEY(WS-IX-1) TO WS-R08-F019
               MOVE 'T' TO WS-R08-F029
           ELSE
               MOVE WS-R08-F017 TO WS-TAB-07-KEY(WS-IX-6)
               MOVE WS-REC-09 TO WS-REC-08
           END-IF.
       P0067.
           MOVE 'K' TO WS-R09-F032
           MOVE WS-TAB-00-KEY(WS-IX-3) TO WS-R08-F003
           MOVE SPACES TO WS-R09-G04
           MOVE SPACES TO WS-R08-G01.
       P0068.
           MOVE SPACES TO WS-R08-G03
           MOVE WS-TAB-11-TXT(WS-IX-4) TO WS-R09-F014
           IF WS-R09-F003 = SPACES
               MOVE 'B' TO WS-R09-F001
               MOVE ZERO TO WS-R08-F030
               MOVE SPACES TO WS-R08-G03
               MOVE WS-REC-09 TO WS-REC-08
           ELSE
               MOVE 'Z' TO WS-R09-F010(6:1)
               MOVE 'Z' TO WS-R09-F031(2:1)
               MOVE WS-R09-F013 TO WS-TAB-01-TXT(WS-IX-1)
               MOVE 'H' TO WS-R09-F029
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0072
           END-IF.
       P0069.
           MOVE ZERO TO WS-R09-F011
           MOVE 'Z' TO WS-R09-F004(5:1)
           MOVE WS-REC-09 TO WS-REC-08
           MOVE 'Z' TO WS-R08-F035(2:1).
       P0070.
           MOVE SPACES TO WS-R09-G05
           MOVE 'Y' TO WS-R08-F008
           MOVE 'Q' TO WS-R09-F007
           MOVE ZERO TO WS-R08-F010
           IF WS-R08-F018 = SPACES
               MOVE 'Z' TO WS-R08-F006(2:1)
               MOVE 'Q' TO WS-R08-F017
           ELSE
               MOVE 'Z' TO WS-R09-F004(2:1)
               MOVE WS-R08-F021 TO WS-TAB-09-KEY(WS-IX-6)
           END-IF.
       P0071.
           MOVE 'Z' TO WS-R09-F010(1:1)
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE WS-R08-F033 TO WS-RDF-06-HEAD
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'M' TO WS-R09-F023
               MOVE 'Z' TO WS-R08-F016(6:1)
             WHEN 'B2'
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE WS-REC-09 TO WS-REC-08
             WHEN 'C3'
               MOVE 'W' TO WS-R09-F024
               MOVE SPACES TO WS-R09-G02
             WHEN OTHER
               MOVE WS-TAB-05-KEY(WS-IX-3) TO WS-R09-F017
               COMPUTE WS-IX-5 = WS-IX-5 + 1
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0072
           END-IF.
       P0072.
           MOVE WS-REC-08 TO WS-REC-09
           MOVE 'I' TO WS-R09-F004
           MOVE WS-R09-F009 TO WS-RDF-09-MID
           MOVE 'D' TO WS-R09-F000
           IF WS-R08-F029 = SPACES
               MOVE ZERO TO WS-R08-F031
               MOVE WS-TAB-10-KEY(WS-IX-0) TO WS-R08-F021
               MOVE 'M' TO WS-R09-F005
               MOVE 'E' TO WS-R09-F003
           ELSE
               MOVE 'L' TO WS-R08-F007
               COMPUTE WS-IX-2 = WS-IX-2 + 1
           END-IF
           CONTINUE.
       P0073.
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           MOVE WS-TAB-11-TXT(WS-IX-0) TO WS-R10-F034
           MOVE 'X' TO WS-R09-F027
           IF WS-R10-F007 = SPACES
               MOVE WS-REC-10 TO WS-REC-09
               COMPUTE WS-IX-0 = WS-IX-0 + 1
           ELSE
               MOVE ZERO TO WS-R09-F008
               MOVE WS-REC-09 TO WS-REC-10
           END-IF.
       P0074.
           MOVE WS-TAB-06-TXT(WS-IX-4) TO WS-R10-F024
           MOVE WS-R09-F013 TO WS-TAB-04-KEY(WS-IX-5)
           MOVE 'G' TO WS-R09-F029
           IF WS-R09-F026 = SPACES
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'Z' TO WS-R09-F004(4:1)
               MOVE 'W' TO WS-R09-F003
           ELSE
               MOVE ZERO TO WS-R09-F011
               MOVE SPACES TO WS-R10-G04
           END-IF.
       P0075.
           MOVE WS-REC-09 TO WS-REC-10
           MOVE ZERO TO WS-R10-F019
           MOVE SPACES TO WS-R09-G03
           IF WS-R09-F025 = SPACES
               MOVE WS-REC-10 TO WS-REC-09
               MOVE 'Z' TO WS-R09-F018(10:1)
               MOVE WS-R09-F002 TO WS-RDF-09-HEAD
           ELSE
               MOVE WS-REC-10 TO WS-REC-09
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'Z' TO WS-R09-F027(2:1)
               MOVE WS-R09-F019 TO WS-RDF-09-HEAD
           END-IF.
       P0076.
           MOVE ZERO TO WS-R09-F033
           MOVE WS-REC-10 TO WS-REC-09
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-09 TO WS-REC-10
               COMPUTE WS-IX-2 = WS-IX-2 + 1
             WHEN 'B2'
               MOVE WS-R09-F029 TO WS-TAB-08-KEY(WS-IX-4)
               MOVE SPACES TO WS-R09-G04
               MOVE WS-TAB-01-TXT(WS-IX-7) TO WS-R09-F027
             WHEN 'C3'
               MOVE WS-REC-10 TO WS-REC-09
               COMPUTE WS-IX-6 = WS-IX-6 + 1
             WHEN OTHER
               MOVE ZERO TO WS-R09-F021
               MOVE 'Z' TO WS-R10-F033(11:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0080
           END-IF.
       P0077.
           MOVE 'L' TO WS-R10-F016
           MOVE 'F' TO WS-R10-F003
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R10-G00
               MOVE WS-REC-10 TO WS-REC-09
             WHEN 'B2'
               MOVE WS-R10-F024 TO WS-TAB-09-TXT(WS-IX-7)
               MOVE SPACES TO WS-R09-G04
               MOVE SPACES TO WS-R09-G02
             WHEN 'C3'
               MOVE ZERO TO WS-R09-F008
               MOVE 'X' TO WS-R10-F009
               MOVE 'W' TO WS-R10-F009
             WHEN OTHER
               MOVE 'Q' TO WS-R10-F034
               MOVE WS-REC-10 TO WS-REC-09
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0080
           END-IF.
       P0078.
           MOVE ZERO TO WS-R10-F019
           MOVE WS-REC-09 TO WS-REC-10
           MOVE 'Z' TO WS-R10-F015(6:1)
           MOVE 'Z' TO WS-R09-F028(11:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R10-F000
               MOVE WS-REC-09 TO WS-REC-10
               MOVE WS-TAB-07-TXT(WS-IX-7) TO WS-R09-F035
             WHEN 'B2'
               MOVE 'Z' TO WS-R10-F032
               COMPUTE WS-IX-7 = WS-IX-7 + 1
             WHEN 'C3'
               MOVE 'T' TO WS-R10-F013
               MOVE 'L' TO WS-R09-F002
             WHEN OTHER
               MOVE WS-REC-09 TO WS-REC-10
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE WS-R09-F002 TO WS-TAB-02-KEY(WS-IX-6)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0080
           END-IF.
       P0079.
           MOVE 'B' TO WS-R09-F028
           MOVE ZERO TO WS-R09-F015
           IF WS-FLAG = 'Y'
               GO TO P0080
           END-IF.
       P0080.
           MOVE WS-TAB-02-KEY(WS-IX-6) TO WS-R09-F024
           MOVE WS-TAB-06-KEY(WS-IX-6) TO WS-R09-F011
           IF WS-R10-F002 = ZERO
               MOVE SPACES TO WS-R09-G00
               MOVE ZERO TO WS-R09-F021
           ELSE
               MOVE WS-REC-09 TO WS-REC-10
               MOVE 'Z' TO WS-R09-F025(3:1)
           END-IF
           CONTINUE.
       P0081.
           MOVE WS-R11-F014 TO WS-RDF-09-MID
           MOVE 'H' TO WS-R11-F021.
       P0082.
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           MOVE SPACES TO WS-R10-G02
           MOVE 'Z' TO WS-R10-F007(15:1)
           MOVE 'Z' TO WS-R10-F004(2:1)
           IF WS-FLAG = 'Y'
               GO TO P0088
           END-IF.
       P0083.
           MOVE 'Q' TO WS-R11-F014
           MOVE WS-R11-F030 TO WS-RDF-09-TAIL
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R10-F000
               MOVE 'Z' TO WS-R11-F029(1:1)
               MOVE WS-TAB-05-TXT(WS-IX-6) TO WS-R10-F024
             WHEN 'B2'
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE ZERO TO WS-R11-F012
               MOVE SPACES TO WS-R10-G05
             WHEN 'C3'
               MOVE SPACES TO WS-R11-G02
               MOVE WS-R10-F005 TO WS-TAB-01-KEY(WS-IX-7)
               MOVE WS-REC-11 TO WS-REC-10
             WHEN OTHER
               MOVE 'Q' TO WS-R10-F000
               MOVE WS-REC-10 TO WS-REC-11
               MOVE ZERO TO WS-R10-F014
           END-EVALUATE.
       P0084.
           MOVE WS-REC-11 TO WS-REC-10
           MOVE WS-REC-11 TO WS-REC-10
           MOVE SPACES TO WS-R11-G02
           IF WS-R11-F011 = SPACES
               MOVE WS-R10-F035 TO WS-RDF-09-TAIL
               MOVE 'V' TO WS-R11-F015
               MOVE WS-R10-F005 TO WS-RDF-09-HEAD
               MOVE WS-R10-F006 TO WS-TAB-02-KEY(WS-IX-4)
           ELSE
               MOVE WS-R11-F020 TO WS-TAB-04-TXT(WS-IX-0)
               MOVE WS-REC-10 TO WS-REC-11
               MOVE ZERO TO WS-R10-F010
           END-IF.
       P0085.
           MOVE WS-TAB-09-KEY(WS-IX-2) TO WS-R10-F017
           MOVE WS-TAB-04-KEY(WS-IX-5) TO WS-R10-F021
           MOVE 'I' TO WS-R10-F028
           IF WS-FLAG = 'Y'
               GO TO P0088
           END-IF.
       P0086.
           MOVE 'U' TO WS-R10-F008
           MOVE ZERO TO WS-R11-F020
           MOVE SPACES TO WS-R11-G03
           MOVE WS-TAB-10-KEY(WS-IX-0) TO WS-R11-F013.
       P0087.
           MOVE SPACES TO WS-R10-G04
           MOVE 'E' TO WS-R10-F021
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           IF WS-FLAG = 'Y'
               GO TO P0081
           END-IF.
       P0088.
           MOVE WS-TAB-09-TXT(WS-IX-5) TO WS-R10-F020
           MOVE ZERO TO WS-R10-F014
           MOVE WS-R11-F000 TO WS-RDF-09-MID
           IF WS-R11-F006 = SPACES
               MOVE SPACES TO WS-R10-G02
               MOVE SPACES TO WS-R10-G02
               MOVE 'P' TO WS-R11-F010
               MOVE WS-R10-F022 TO WS-RDF-09-TAIL
           ELSE
               MOVE SPACES TO WS-R10-G02
               MOVE ZERO TO WS-R10-F031
               MOVE 'Z' TO WS-R10-F008(4:1)
           END-IF
           CONTINUE.
       P0089.
           MOVE SPACES TO WS-R11-G01
           MOVE 'Z' TO WS-R11-F015(4:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R11-F006 TO WS-RDF-09-MID
               MOVE WS-R12-F004 TO WS-RDF-09-MID
             WHEN 'B2'
               MOVE 'Z' TO WS-R12-F029(7:1)
               MOVE 'F' TO WS-R12-F032
               MOVE WS-REC-11 TO WS-REC-12
             WHEN 'C3'
               MOVE SPACES TO WS-R11-G02
               MOVE 'Z' TO WS-R12-F029(6:1)
             WHEN OTHER
               MOVE WS-R11-F003 TO WS-RDF-12-TAIL
               MOVE WS-REC-12 TO WS-REC-11
               MOVE WS-TAB-04-TXT(WS-IX-2) TO WS-R12-F018
           END-EVALUATE.
       P0090.
           MOVE ZERO TO WS-R11-F020
           MOVE 'R' TO WS-R12-F010
           MOVE SPACES TO WS-R12-G02
           MOVE WS-REC-11 TO WS-REC-12
           IF WS-R11-F019 = SPACES
               MOVE SPACES TO WS-R11-G04
               MOVE ZERO TO WS-R12-F033
           ELSE
               MOVE WS-TAB-03-KEY(WS-IX-6) TO WS-R11-F017
               MOVE WS-REC-12 TO WS-REC-11
           END-IF.
       P0091.
           MOVE 'P' TO WS-R12-F006
           MOVE WS-TAB-03-KEY(WS-IX-0) TO WS-R12-F021
           MOVE WS-REC-11 TO WS-REC-12
           IF WS-R11-F033 = ZERO
               MOVE WS-R12-F018 TO WS-TAB-05-TXT(WS-IX-1)
               MOVE WS-R11-F019 TO WS-TAB-07-KEY(WS-IX-3)
               MOVE 'W' TO WS-R11-F013
           ELSE
               MOVE 'S' TO WS-R11-F021
               MOVE WS-REC-11 TO WS-REC-12
               MOVE WS-R12-F028 TO WS-TAB-00-KEY(WS-IX-4)
               MOVE WS-REC-11 TO WS-REC-12
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0096
           END-IF.
       P0092.
           MOVE 'C' TO WS-R12-F022
           MOVE ZERO TO WS-R12-F023
           MOVE WS-REC-11 TO WS-REC-12
           IF WS-R11-F012 = ZERO
               MOVE 'K' TO WS-R12-F010
               MOVE 'H' TO WS-R12-F006
           ELSE
               MOVE 'C' TO WS-R12-F019
               MOVE SPACES TO WS-R11-G00
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0096
           END-IF.
       P0093.
           MOVE WS-REC-12 TO WS-REC-11
           MOVE SPACES TO WS-R12-G04
           MOVE WS-R12-F024 TO WS-TAB-04-KEY(WS-IX-1)
           MOVE WS-REC-11 TO WS-REC-12.
       P0094.
           MOVE WS-REC-12 TO WS-REC-11
           MOVE WS-REC-12 TO WS-REC-11
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'F' TO WS-R11-F035
               MOVE WS-R11-F000 TO WS-RDF-12-HEAD
               MOVE SPACES TO WS-R12-G01
             WHEN 'B2'
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE 'Z' TO WS-R11-F014(13:1)
               MOVE WS-REC-11 TO WS-REC-12
             WHEN 'C3'
               MOVE WS-R12-F035 TO WS-RDF-12-TAIL
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE WS-R12-F030 TO WS-RDF-09-MID
             WHEN OTHER
               MOVE 'L' TO WS-R11-F016
               MOVE 'S' TO WS-R12-F035
           END-EVALUATE.
       P0095.
           MOVE ZERO TO WS-R12-F028
           MOVE SPACES TO WS-R11-G03
           MOVE 'B' TO WS-R11-F023
           MOVE 'Y' TO WS-R11-F015
           IF WS-FLAG = 'Y'
               GO TO P0089
           END-IF.
       P0096.
           MOVE 'Q' TO WS-R12-F001
           MOVE ZERO TO WS-R11-F004
           MOVE WS-TAB-07-TXT(WS-IX-5) TO WS-R11-F027
           MOVE 'Z' TO WS-R12-F022(12:1)
           CONTINUE.
       P0097.
           MOVE 'Z' TO WS-R12-F029(7:1)
           MOVE 'Q' TO WS-R12-F032
           MOVE 'Z' TO WS-R12-F002(2:1)
           MOVE 'N' TO WS-R13-F010
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R13-F003(4:1)
               MOVE ZERO TO WS-R13-F024
               MOVE WS-REC-12 TO WS-REC-13
             WHEN 'B2'
               MOVE WS-REC-12 TO WS-REC-13
               MOVE WS-R13-F017 TO WS-TAB-07-KEY(WS-IX-4)
               MOVE WS-R12-F020 TO WS-RDF-12-TAIL
             WHEN 'C3'
               MOVE 'K' TO WS-R12-F031
               MOVE WS-REC-12 TO WS-REC-13
               MOVE 'E' TO WS-R12-F024
             WHEN OTHER
               MOVE WS-REC-13 TO WS-REC-12
               MOVE 'Q' TO WS-R12-F032
               MOVE WS-R12-F023 TO WS-RDF-12-MID
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0104
           END-IF.
       P0098.
           MOVE WS-REC-13 TO WS-REC-12
           MOVE SPACES TO WS-R12-G04
           MOVE 'Z' TO WS-R12-F026(1:1)
           IF WS-R12-F029 = ZERO
               MOVE 'Z' TO WS-R12-F030(2:1)
               MOVE 'Z' TO WS-R13-F005(1:1)
           ELSE
               MOVE 'Z' TO WS-R12-F011(9:1)
               MOVE WS-REC-12 TO WS-REC-13
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0104
           END-IF.
       P0099.
           MOVE WS-REC-12 TO WS-REC-13
           MOVE ZERO TO WS-R13-F015
           MOVE ZERO TO WS-R13-F018
           IF WS-R12-F031 = SPACES
               MOVE 'Q' TO WS-R12-F004
               MOVE WS-R13-F024 TO WS-TAB-04-TXT(WS-IX-4)
           ELSE
               MOVE WS-REC-13 TO WS-REC-12
               MOVE 'Y' TO WS-R12-F022
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0104
           END-IF.
       P0100.
           MOVE SPACES TO WS-R12-G02
           MOVE WS-R12-F011 TO WS-TAB-11-TXT(WS-IX-7)
           MOVE SPACES TO WS-R12-G00
           IF WS-FLAG = 'Y'
               GO TO P0097
           END-IF.
       P0101.
           MOVE ZERO TO WS-R13-F008
           MOVE 'Q' TO WS-R12-F021
           MOVE WS-REC-13 TO WS-REC-12
           IF WS-R13-F011 = SPACES
               MOVE SPACES TO WS-R13-G02
               MOVE WS-TAB-09-KEY(WS-IX-4) TO WS-R13-F000
               MOVE 'Q' TO WS-R12-F014
               MOVE ZERO TO WS-R13-F032
           ELSE
               MOVE 'V' TO WS-R13-F006
               MOVE WS-TAB-05-KEY(WS-IX-2) TO WS-R13-F017
               MOVE ZERO TO WS-R13-F015
               MOVE WS-REC-12 TO WS-REC-13
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0097
           END-IF.
       P0102.
           MOVE WS-R13-F011 TO WS-TAB-07-KEY(WS-IX-2)
           MOVE SPACES TO WS-R13-G05
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-12 TO WS-REC-13
               MOVE 'Z' TO WS-R12-F023(3:1)
               MOVE WS-R12-F021 TO WS-TAB-08-TXT(WS-IX-2)
             WHEN 'B2'
               MOVE SPACES TO WS-R13-G05
               MOVE WS-REC-13 TO WS-REC-12
               MOVE 'R' TO WS-R12-F025
             WHEN 'C3'
               MOVE WS-R13-F010 TO WS-TAB-09-TXT(WS-IX-2)
               MOVE WS-R12-F013 TO WS-RDF-12-TAIL
               MOVE WS-REC-12 TO WS-REC-13
             WHEN OTHER
               MOVE WS-REC-12 TO WS-REC-13
               MOVE WS-REC-13 TO WS-REC-12
               COMPUTE WS-IX-3 = WS-IX-3 + 1
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0097
           END-IF.
       P0103.
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE 'Z' TO WS-R12-F015(1:1).
       P0104.
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE 'A' TO WS-R13-F034
           CONTINUE.
       P0105.
           MOVE ZERO TO WS-R14-F034
           MOVE 'Z' TO WS-R13-F018(4:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R13-F034 TO WS-TAB-03-KEY(WS-IX-4)
               MOVE 'H' TO WS-R13-F005
               MOVE WS-REC-14 TO WS-REC-13
             WHEN 'B2'
               MOVE 'Z' TO WS-R14-F026(1:1)
               MOVE 'Q' TO WS-R14-F009
               MOVE ZERO TO WS-R13-F020
             WHEN 'C3'
               MOVE 'Z' TO WS-R14-F015(3:1)
               MOVE WS-REC-14 TO WS-REC-13
               MOVE 'Z' TO WS-R13-F026(4:1)
             WHEN OTHER
               MOVE WS-R13-F033 TO WS-TAB-05-TXT(WS-IX-1)
               MOVE SPACES TO WS-R14-G03
               MOVE WS-REC-14 TO WS-REC-13
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0112
           END-IF.
       P0106.
           MOVE WS-TAB-10-TXT(WS-IX-6) TO WS-R14-F023
           MOVE 'Z' TO WS-R14-F019(1:1)
           IF WS-R13-F012 = SPACES
               MOVE WS-REC-14 TO WS-REC-13
               MOVE 'Z' TO WS-R14-F019(2:1)
           ELSE
               MOVE SPACES TO WS-R13-G05
               MOVE WS-REC-13 TO WS-REC-14
               MOVE WS-REC-14 TO WS-REC-13
           END-IF.
       P0107.
           MOVE WS-R13-F004 TO WS-RDF-12-MID
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R13-F029(3:1)
               MOVE 'Z' TO WS-R14-F011(4:1)
               MOVE WS-REC-13 TO WS-REC-14
             WHEN 'B2'
               MOVE 'B' TO WS-R13-F012
               MOVE WS-R13-F031 TO WS-TAB-00-KEY(WS-IX-3)
             WHEN 'C3'
               MOVE WS-R13-F023 TO WS-TAB-04-TXT(WS-IX-7)
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'D' TO WS-R14-F016
             WHEN OTHER
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'O' TO WS-R13-F013
           END-EVALUATE.
       P0108.
           MOVE WS-R13-F004 TO WS-RDF-12-MID
           MOVE 'N' TO WS-R14-F013
           IF WS-R14-F032 = ZERO
               MOVE 'X' TO WS-R14-F029
               MOVE 'S' TO WS-R14-F019
               MOVE WS-TAB-07-TXT(WS-IX-4) TO WS-R13-F022
           ELSE
               MOVE SPACES TO WS-R13-G04
               MOVE SPACES TO WS-R13-G04
               MOVE WS-REC-13 TO WS-REC-14
           END-IF.
       P0109.
           MOVE WS-R14-F026 TO WS-RDF-12-MID
           MOVE 'Z' TO WS-R13-F024(4:1)
           MOVE WS-TAB-04-KEY(WS-IX-6) TO WS-R13-F026
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R14-F005
               MOVE WS-REC-14 TO WS-REC-13
             WHEN 'B2'
               MOVE WS-REC-13 TO WS-REC-14
               MOVE WS-REC-14 TO WS-REC-13
             WHEN 'C3'
               MOVE 'Z' TO WS-R13-F020(1:1)
               MOVE WS-REC-13 TO WS-REC-14
               MOVE WS-REC-14 TO WS-REC-13
             WHEN OTHER
               MOVE WS-REC-14 TO WS-REC-13
               MOVE 'D' TO WS-R14-F013
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0105
           END-IF.
       P0110.
           MOVE 'M' TO WS-R14-F012
           MOVE 'Q' TO WS-R13-F035
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R13-F025
               MOVE SPACES TO WS-R14-G04
               MOVE 'T' TO WS-R13-F019
             WHEN 'B2'
               MOVE SPACES TO WS-R13-G03
               MOVE WS-REC-14 TO WS-REC-13
             WHEN 'C3'
               MOVE ZERO TO WS-R13-F008
               MOVE WS-REC-13 TO WS-REC-14
               MOVE ZERO TO WS-R13-F002
             WHEN OTHER
               MOVE 'Z' TO WS-R13-F010(1:1)
               MOVE 'Z' TO WS-R14-F030(1:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0112
           END-IF.
       P0111.
           MOVE 'K' TO WS-R13-F030
           MOVE WS-R14-F033 TO WS-TAB-00-TXT(WS-IX-1)
           MOVE WS-REC-13 TO WS-REC-14
           IF WS-R14-F018 = SPACES
               MOVE SPACES TO WS-R14-G05
               MOVE WS-REC-14 TO WS-REC-13
               MOVE ZERO TO WS-R14-F005
               MOVE ZERO TO WS-R13-F035
           ELSE
               MOVE 'Z' TO WS-R13-F010(1:1)
               MOVE WS-R13-F029 TO WS-TAB-07-TXT(WS-IX-5)
               MOVE 'Z' TO WS-R14-F001(5:1)
               MOVE 'Q' TO WS-R14-F016
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0112
           END-IF.
       P0112.
           MOVE WS-R13-F026 TO WS-RDF-12-MID
           MOVE SPACES TO WS-R13-G04
           IF WS-R13-F001 = SPACES
               MOVE SPACES TO WS-R14-G05
               MOVE WS-REC-14 TO WS-REC-13
               MOVE SPACES TO WS-R13-G02
               MOVE 'Z' TO WS-R13-F013(1:1)
           ELSE
               MOVE 'Z' TO WS-R14-F031(2:1)
               MOVE WS-REC-13 TO WS-REC-14
               MOVE 'G' TO WS-R14-F018
           END-IF
           CONTINUE.
       P0113.
           MOVE 'Z' TO WS-R15-F035(2:1)
           MOVE 'Q' TO WS-R15-F015
           MOVE 'E' TO WS-R15-F013.
       P0114.
           MOVE WS-REC-14 TO WS-REC-15
           MOVE 'Q' TO WS-R14-F009
           MOVE 'Z' TO WS-R14-F022(3:1)
           IF WS-FLAG = 'Y'
               GO TO P0113
           END-IF.
       P0115.
           MOVE 'R' TO WS-R14-F023
           MOVE 'Z' TO WS-R14-F021(1:1)
           MOVE SPACES TO WS-R14-G03
           MOVE 'Q' TO WS-R14-F013
           IF WS-R14-F019 = SPACES
               MOVE ZERO TO WS-R15-F006
               MOVE WS-R14-F010 TO WS-RDF-15-MID
               MOVE ZERO TO WS-R15-F014
               COMPUTE WS-IX-6 = WS-IX-6 + 1
           ELSE
               MOVE 'O' TO WS-R14-F001
               COMPUTE WS-IX-6 = WS-IX-6 + 1
           END-IF.
       P0116.
           MOVE WS-R14-F032 TO WS-RDF-12-MID
           MOVE 'O' TO WS-R14-F012
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-15 TO WS-REC-14
               MOVE SPACES TO WS-R14-G02
               MOVE WS-REC-14 TO WS-REC-15
             WHEN 'B2'
               MOVE WS-R14-F034 TO WS-TAB-02-TXT(WS-IX-7)
               MOVE SPACES TO WS-R15-G04
             WHEN 'C3'
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE 'Q' TO WS-R14-F006
               MOVE 'B' TO WS-R14-F013
             WHEN OTHER
               MOVE ZERO TO WS-R14-F033
               MOVE 'Z' TO WS-R15-F019(2:1)
               MOVE 'Y' TO WS-R15-F023
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0120
           END-IF.
       P0117.
           MOVE WS-REC-14 TO WS-REC-15
           MOVE SPACES TO WS-R14-G03
           MOVE 'Z' TO WS-R14-F024(6:1)
           MOVE WS-R14-F005 TO WS-RDF-15-MID
           IF WS-FLAG = 'Y'
               GO TO P0120
           END-IF.
       P0118.
           MOVE WS-REC-15 TO WS-REC-14
           MOVE WS-REC-15 TO WS-REC-14
           IF WS-FLAG = 'Y'
               GO TO P0113
           END-IF.
       P0119.
           MOVE 'Z' TO WS-R15-F017(2:1)
           MOVE WS-REC-14 TO WS-REC-15
           MOVE WS-REC-15 TO WS-REC-14
           IF WS-R14-F028 = SPACES
               MOVE WS-REC-14 TO WS-REC-15
               MOVE WS-TAB-07-KEY(WS-IX-7) TO WS-R15-F011
           ELSE
               MOVE 'U' TO WS-R15-F013
               MOVE 'P' TO WS-R14-F008
               MOVE 'P' TO WS-R14-F013
               MOVE WS-REC-14 TO WS-REC-15
           END-IF.
       P0120.
           MOVE WS-REC-15 TO WS-REC-14
           MOVE WS-REC-15 TO WS-REC-14
           MOVE 'Q' TO WS-R14-F000
           MOVE WS-R15-F023 TO WS-TAB-03-TXT(WS-IX-5)
           IF WS-R14-F006 = SPACES
               MOVE 'S' TO WS-R15-F015
               MOVE WS-TAB-10-TXT(WS-IX-0) TO WS-R15-F019
               MOVE 'Q' TO WS-R14-F018
               MOVE 'Q' TO WS-R15-F025
           ELSE
               MOVE 'Z' TO WS-R15-F032(1:1)
               MOVE 'Z' TO WS-R14-F001(3:1)
               MOVE 'Y' TO WS-R14-F007
           END-IF
           CONTINUE.
       P0121.
           MOVE WS-REC-15 TO WS-REC-16
           MOVE 'H' TO WS-R16-F012.
       P0122.
           MOVE WS-REC-15 TO WS-REC-16
           MOVE 'E' TO WS-R16-F008
           MOVE WS-TAB-02-KEY(WS-IX-4) TO WS-R16-F011
           MOVE WS-R15-F020 TO WS-TAB-00-KEY(WS-IX-1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-16 TO WS-REC-15
               MOVE SPACES TO WS-R15-G02
               MOVE WS-REC-15 TO WS-REC-16
             WHEN 'B2'
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE WS-R15-F006 TO WS-TAB-03-TXT(WS-IX-0)
             WHEN 'C3'
               MOVE WS-R15-F016 TO WS-TAB-10-KEY(WS-IX-5)
               MOVE 'Q' TO WS-R15-F018
             WHEN OTHER
               MOVE 'T' TO WS-R15-F032
               MOVE WS-REC-16 TO WS-REC-15
               MOVE 'V' TO WS-R15-F002
           END-EVALUATE.
       P0123.
           MOVE ZERO TO WS-R15-F012
           MOVE WS-R16-F033 TO WS-TAB-10-KEY(WS-IX-7)
           IF WS-R15-F011 = SPACES
               MOVE SPACES TO WS-R15-G00
               MOVE WS-REC-16 TO WS-REC-15
           ELSE
               MOVE ZERO TO WS-R15-F006
               COMPUTE WS-IX-6 = WS-IX-6 + 1
           END-IF.
       P0124.
           MOVE WS-REC-16 TO WS-REC-15
           MOVE 'W' TO WS-R16-F019
           IF WS-FLAG = 'Y'
               GO TO P0128
           END-IF.
       P0125.
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE 'J' TO WS-R16-F000
           IF WS-R15-F015 = SPACES
               MOVE 'U' TO WS-R15-F024
               MOVE WS-R15-F011 TO WS-TAB-04-KEY(WS-IX-6)
               MOVE 'P' TO WS-R15-F032
           ELSE
               MOVE ZERO TO WS-R15-F029
               MOVE 'Z' TO WS-R15-F020(9:1)
               MOVE 'P' TO WS-R15-F000
           END-IF.
       P0126.
           MOVE 'R' TO WS-R15-F015
           MOVE 'Q' TO WS-R15-F010
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'O' TO WS-R16-F021
               MOVE ZERO TO WS-R16-F025
             WHEN 'B2'
               MOVE WS-R15-F032 TO WS-RDF-15-HEAD
               MOVE 'Q' TO WS-R15-F002
               MOVE ZERO TO WS-R15-F003
             WHEN 'C3'
               MOVE 'N' TO WS-R15-F027
               MOVE WS-R15-F025 TO WS-TAB-07-KEY(WS-IX-6)
               MOVE WS-R16-F012 TO WS-RDF-15-MID
             WHEN OTHER
               MOVE 'U' TO WS-R16-F022
               MOVE 'D' TO WS-R16-F013
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0121
           END-IF.
       P0127.
           MOVE ZERO TO WS-R16-F016
           MOVE 'Q' TO WS-R16-F017
           IF WS-R15-F021 = SPACES
               MOVE 'Q' TO WS-R16-F018
               MOVE 'K' TO WS-R16-F013
               MOVE WS-R16-F027 TO WS-RDF-15-HEAD
               MOVE WS-REC-15 TO WS-REC-16
           ELSE
               MOVE 'G' TO WS-R15-F010
               MOVE 'O' TO WS-R16-F002
           END-IF.
       P0128.
           MOVE WS-REC-15 TO WS-REC-16
           MOVE 'Z' TO WS-R15-F011(13:1)
           MOVE SPACES TO WS-R16-G02
           IF WS-R15-F008 = ZERO
               MOVE 'Z' TO WS-R15-F028(4:1)
               MOVE WS-REC-16 TO WS-REC-15
               MOVE WS-REC-16 TO WS-REC-15
           ELSE
               MOVE ZERO TO WS-R15-F029
               MOVE 'F' TO WS-R16-F023
               MOVE SPACES TO WS-R16-G05
           END-IF
           CONTINUE.
       P0129.
           MOVE WS-R17-F035 TO WS-TAB-02-KEY(WS-IX-6)
           MOVE WS-R16-F030 TO WS-RDF-15-TAIL
           MOVE 'Z' TO WS-R16-F012(18:1)
           IF WS-R17-F006 = SPACES
               MOVE WS-TAB-00-TXT(WS-IX-0) TO WS-R17-F020
               MOVE 'Z' TO WS-R17-F002(8:1)
               MOVE 'J' TO WS-R16-F028
               MOVE SPACES TO WS-R17-G04
           ELSE
               MOVE 'Q' TO WS-R17-F012
               MOVE WS-REC-16 TO WS-REC-17
               MOVE 'Z' TO WS-R17-F013(6:1)
           END-IF.
       P0130.
           MOVE 'T' TO WS-R17-F034
           MOVE WS-R17-F024 TO WS-TAB-07-KEY(WS-IX-0)
           MOVE WS-TAB-11-KEY(WS-IX-4) TO WS-R17-F001.
       P0131.
           MOVE 'T' TO WS-R17-F026
           MOVE SPACES TO WS-R16-G02
           IF WS-R17-F014 = SPACES
               MOVE 'S' TO WS-R16-F024
               MOVE SPACES TO WS-R17-G05
           ELSE
               MOVE WS-REC-16 TO WS-REC-17
               MOVE 'N' TO WS-R17-F029
               MOVE 'J' TO WS-R17-F022
           END-IF.
       P0132.
           MOVE 'Q' TO WS-R17-F035
           MOVE 'H' TO WS-R16-F001
           MOVE 'Y' TO WS-R17-F005
           MOVE SPACES TO WS-R17-G02
           IF WS-R17-F007 = SPACES
               MOVE 'Q' TO WS-R16-F001
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE SPACES TO WS-R17-G00
               MOVE 'Z' TO WS-R17-F007(4:1)
           ELSE
               MOVE SPACES TO WS-R17-G00
               MOVE 'J' TO WS-R17-F027
               MOVE 'Y' TO WS-R17-F030
               MOVE WS-TAB-00-TXT(WS-IX-5) TO WS-R17-F017
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0129
           END-IF.
       P0133.
           MOVE 'T' TO WS-R16-F033
           MOVE 'Z' TO WS-R16-F030(4:1)
           IF WS-R16-F031 = SPACES
               MOVE WS-REC-17 TO WS-REC-16
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'Z' TO WS-R16-F024(4:1)
               MOVE 'G' TO WS-R17-F024
           ELSE
               MOVE 'Q' TO WS-R16-F005
               MOVE WS-REC-17 TO WS-REC-16
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0136
           END-IF.
       P0134.
           MOVE WS-R16-F019 TO WS-RDF-15-TAIL
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           IF WS-R17-F002 = SPACES
               MOVE 'Z' TO WS-R17-F007
               MOVE 'A' TO WS-R17-F008
               MOVE WS-R16-F025 TO WS-RDF-15-HEAD
           ELSE
               MOVE WS-REC-17 TO WS-REC-16
               MOVE WS-REC-17 TO WS-REC-16
               MOVE WS-REC-17 TO WS-REC-16
               MOVE 'Z' TO WS-R17-F016(4:1)
           END-IF.
       P0135.
           MOVE 'Z' TO WS-R17-F013
           MOVE WS-TAB-07-TXT(WS-IX-4) TO WS-R17-F007
           IF WS-R16-F003 = SPACES
               MOVE WS-REC-17 TO WS-REC-16
               MOVE SPACES TO WS-R16-G05
           ELSE
               MOVE 'Q' TO WS-R16-F005
               MOVE WS-REC-17 TO WS-REC-16
           END-IF.
       P0136.
           MOVE WS-TAB-04-TXT(WS-IX-0) TO WS-R17-F016
           MOVE 'G' TO WS-R17-F023
           MOVE WS-TAB-03-KEY(WS-IX-3) TO WS-R16-F018
           MOVE 'Q' TO WS-R16-F034
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R17-F017 TO WS-RDF-15-MID
               MOVE 'Z' TO WS-R17-F028(4:1)
               MOVE 'Q' TO WS-R16-F005
             WHEN 'B2'
               MOVE 'Z' TO WS-R17-F027(4:1)
               MOVE SPACES TO WS-R17-G01
               MOVE ZERO TO WS-R16-F035
             WHEN 'C3'
               MOVE WS-REC-16 TO WS-REC-17
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'Q' TO WS-R17-F032
             WHEN OTHER
               MOVE SPACES TO WS-R16-G01
               MOVE WS-REC-17 TO WS-REC-16
               MOVE ZERO TO WS-R16-F015
           END-EVALUATE
           CONTINUE.
       P0137.
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           IF WS-R18-F016 = SPACES
               MOVE 'Q' TO WS-R17-F018
               MOVE 'Z' TO WS-R18-F023(2:1)
               MOVE SPACES TO WS-R18-G04
               MOVE WS-R17-F026 TO WS-TAB-05-TXT(WS-IX-1)
           ELSE
               MOVE WS-TAB-05-TXT(WS-IX-2) TO WS-R17-F006
               MOVE 'E' TO WS-R17-F006
               MOVE 'C' TO WS-R18-F017
               MOVE 'Q' TO WS-R18-F035
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0144
           END-IF.
       P0138.
           MOVE 'T' TO WS-R18-F002
           MOVE WS-REC-17 TO WS-REC-18
           MOVE WS-TAB-06-KEY(WS-IX-7) TO WS-R18-F021
           IF WS-R18-F010 = ZERO
               MOVE WS-REC-17 TO WS-REC-18
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE WS-R17-F032 TO WS-TAB-03-TXT(WS-IX-7)
           ELSE
               MOVE ZERO TO WS-R18-F010
               MOVE WS-REC-18 TO WS-REC-17
           END-IF.
       P0139.
           MOVE WS-R18-F024 TO WS-TAB-01-KEY(WS-IX-7)
           MOVE 'H' TO WS-R18-F016
           MOVE 'Z' TO WS-R17-F015(8:1)
           IF WS-R18-F020 = SPACES
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'X' TO WS-R17-F023
               MOVE WS-R18-F005 TO WS-TAB-05-KEY(WS-IX-1)
               MOVE 'U' TO WS-R17-F022
           ELSE
               MOVE 'O' TO WS-R17-F004
               MOVE SPACES TO WS-R17-G01
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               COMPUTE WS-IX-4 = WS-IX-4 + 1
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0144
           END-IF.
       P0140.
           MOVE 'J' TO WS-R17-F019
           MOVE 'G' TO WS-R18-F020
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-TAB-02-TXT(WS-IX-6) TO WS-R18-F003
               MOVE WS-R17-F006 TO WS-RDF-15-MID
             WHEN 'B2'
               MOVE WS-TAB-10-TXT(WS-IX-4) TO WS-R17-F022
               MOVE 'E' TO WS-R17-F034
               MOVE SPACES TO WS-R18-G05
             WHEN 'C3'
               MOVE 'Z' TO WS-R17-F026(5:1)
               MOVE SPACES TO WS-R18-G05
               MOVE WS-R18-F019 TO WS-TAB-04-KEY(WS-IX-0)
             WHEN OTHER
               MOVE WS-REC-17 TO WS-REC-18
               MOVE 'J' TO WS-R17-F031
               MOVE WS-R17-F014 TO WS-TAB-05-KEY(WS-IX-0)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0144
           END-IF.
       P0141.
           MOVE WS-R17-F024 TO WS-TAB-09-KEY(WS-IX-6)
           MOVE ZERO TO WS-R18-F022
           IF WS-FLAG = 'Y'
               GO TO P0144
           END-IF.
       P0142.
           MOVE 'Z' TO WS-R18-F009
           COMPUTE WS-IX-4 = WS-IX-4 + 1.
       P0143.
           MOVE 'Z' TO WS-R18-F005(10:1)
           MOVE 'H' TO WS-R17-F011
           MOVE WS-R18-F012 TO WS-RDF-15-HEAD
           MOVE 'U' TO WS-R17-F023
           IF WS-R18-F019 = ZERO
               MOVE 'U' TO WS-R17-F021
               MOVE WS-R17-F014 TO WS-RDF-18-HEAD
               MOVE WS-REC-17 TO WS-REC-18
           ELSE
               MOVE WS-REC-18 TO WS-REC-17
               MOVE SPACES TO WS-R18-G00
               MOVE WS-REC-18 TO WS-REC-17
               MOVE WS-REC-17 TO WS-REC-18
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0137
           END-IF.
       P0144.
           MOVE WS-R17-F019 TO WS-RDF-15-MID
           MOVE ZERO TO WS-R18-F004
           MOVE SPACES TO WS-R18-G01
           MOVE 'E' TO WS-R17-F023
           IF WS-R18-F002 = SPACES
               MOVE 'M' TO WS-R17-F030
               MOVE 'Q' TO WS-R17-F011
               MOVE ZERO TO WS-R18-F022
               COMPUTE WS-IX-1 = WS-IX-1 + 1
           ELSE
               MOVE 'Z' TO WS-R17-F015(9:1)
               MOVE WS-REC-18 TO WS-REC-17
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE WS-REC-17 TO WS-REC-18
           END-IF
           CONTINUE.
       P0145.
           MOVE 'X' TO WS-R18-F018
           MOVE WS-R19-F011 TO WS-TAB-11-TXT(WS-IX-1)
           MOVE SPACES TO WS-R19-G03
           IF WS-R18-F005 = SPACES
               MOVE 'Z' TO WS-R18-F012(2:1)
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'Z' TO WS-R19-F031(7:1)
           ELSE
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'C' TO WS-R18-F017
               MOVE WS-R18-F024 TO WS-TAB-04-TXT(WS-IX-1)
               MOVE WS-R19-F034 TO WS-TAB-08-KEY(WS-IX-4)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0152
           END-IF.
       P0146.
           MOVE WS-REC-18 TO WS-REC-19
           MOVE 'Z' TO WS-R18-F000(4:1)
           IF WS-R18-F006 = SPACES
               MOVE ZERO TO WS-R18-F019
               MOVE ZERO TO WS-R18-F019
               MOVE SPACES TO WS-R19-G03
               MOVE WS-TAB-00-TXT(WS-IX-3) TO WS-R19-F004
           ELSE
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE 'V' TO WS-R18-F016
               MOVE 'Z' TO WS-R18-F016(10:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0152
           END-IF.
       P0147.
           MOVE WS-R19-F026 TO WS-RDF-18-TAIL
           MOVE 'Q' TO WS-R18-F019
           MOVE WS-REC-19 TO WS-REC-18
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R18-F005(4:1)
               MOVE WS-REC-19 TO WS-REC-18
             WHEN 'B2'
               MOVE 'U' TO WS-R19-F021
               MOVE WS-REC-19 TO WS-REC-18
             WHEN 'C3'
               MOVE 'X' TO WS-R19-F026
               MOVE SPACES TO WS-R19-G00
               MOVE ZERO TO WS-R19-F029
             WHEN OTHER
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE WS-R18-F028 TO WS-RDF-18-HEAD
               MOVE 'I' TO WS-R19-F015
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0145
           END-IF.
       P0148.
           MOVE ZERO TO WS-R19-F035
           MOVE 'Y' TO WS-R19-F002
           MOVE WS-R19-F024 TO WS-TAB-11-TXT(WS-IX-2)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R19-F005
               MOVE SPACES TO WS-R18-G05
             WHEN 'B2'
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'K' TO WS-R18-F014
               MOVE WS-REC-19 TO WS-REC-18
             WHEN 'C3'
               MOVE WS-REC-19 TO WS-REC-18
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE WS-R18-F002 TO WS-TAB-02-KEY(WS-IX-2)
             WHEN OTHER
               MOVE ZERO TO WS-R18-F028
               MOVE WS-R19-F011 TO WS-RDF-18-HEAD
               MOVE SPACES TO WS-R19-G04
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0145
           END-IF.
       P0149.
           MOVE ZERO TO WS-R19-F035
           MOVE 'Q' TO WS-R18-F009
           MOVE 'Q' TO WS-R19-F012
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           IF WS-R18-F002 = SPACES
               MOVE WS-R19-F011 TO WS-RDF-18-HEAD
               MOVE WS-REC-18 TO WS-REC-19
           ELSE
               MOVE 'Q' TO WS-R19-F022
               MOVE WS-REC-19 TO WS-REC-18
               MOVE ZERO TO WS-R19-F008
               MOVE WS-REC-18 TO WS-REC-19
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0145
           END-IF.
       P0150.
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE WS-R19-F024 TO WS-RDF-18-TAIL
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-18 TO WS-REC-19
               MOVE 'Z' TO WS-R18-F007(2:1)
               MOVE WS-R18-F023 TO WS-TAB-07-TXT(WS-IX-5)
             WHEN 'B2'
               MOVE WS-REC-18 TO WS-REC-19
               MOVE ZERO TO WS-R18-F022
               MOVE 'Q' TO WS-R18-F003
             WHEN 'C3'
               MOVE 'H' TO WS-R18-F030
               MOVE 'C' TO WS-R18-F026
             WHEN OTHER
               MOVE 'Z' TO WS-R18-F013(2:1)
               MOVE 'S' TO WS-R19-F020
               MOVE WS-R19-F004 TO WS-RDF-18-MID
           END-EVALUATE.
       P0151.
           MOVE 'F' TO WS-R19-F021
           MOVE 'Z' TO WS-R18-F012(2:1)
           MOVE ZERO TO WS-R18-F013.
       P0152.
           MOVE WS-R19-F024 TO WS-TAB-01-TXT(WS-IX-6)
           MOVE SPACES TO WS-R19-G03
           MOVE SPACES TO WS-R19-G02
           IF WS-R19-F034 = ZERO
               MOVE WS-R19-F011 TO WS-RDF-18-MID
               MOVE 'H' TO WS-R18-F030
               MOVE 'Q' TO WS-R19-F014
               MOVE WS-R18-F018 TO WS-RDF-18-TAIL
           ELSE
               MOVE ZERO TO WS-R19-F006
               MOVE WS-REC-19 TO WS-REC-18
           END-IF
           CONTINUE.
       P0153.
           MOVE SPACES TO WS-R20-G05
           MOVE WS-R20-F015 TO WS-RDF-18-HEAD
           MOVE WS-REC-19 TO WS-REC-20
           IF WS-R19-F024 = ZERO
               MOVE WS-R20-F008 TO WS-RDF-18-HEAD
               MOVE 'L' TO WS-R19-F026
               MOVE 'Z' TO WS-R19-F024(5:1)
               MOVE SPACES TO WS-R19-G01
           ELSE
               MOVE WS-R19-F004 TO WS-TAB-08-TXT(WS-IX-0)
               MOVE 'Q' TO WS-R19-F013
               MOVE WS-REC-20 TO WS-REC-19
           END-IF.
       P0154.
           MOVE WS-R20-F021 TO WS-RDF-18-TAIL
           MOVE SPACES TO WS-R19-G01
           MOVE WS-TAB-10-TXT(WS-IX-7) TO WS-R20-F004
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'A' TO WS-R20-F008
               MOVE WS-REC-19 TO WS-REC-20
               MOVE WS-TAB-00-TXT(WS-IX-6) TO WS-R19-F014
             WHEN 'B2'
               MOVE WS-R19-F001 TO WS-TAB-01-TXT(WS-IX-4)
               MOVE WS-R20-F014 TO WS-TAB-10-KEY(WS-IX-3)
             WHEN 'C3'
               MOVE 'Z' TO WS-R20-F030(2:1)
               MOVE 'Z' TO WS-R19-F021(1:1)
               MOVE WS-REC-19 TO WS-REC-20
             WHEN OTHER
               MOVE ZERO TO WS-R20-F007
               MOVE 'L' TO WS-R19-F007
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0153
           END-IF.
       P0155.
           MOVE SPACES TO WS-R20-G04
           MOVE WS-REC-19 TO WS-REC-20
           MOVE WS-R20-F021 TO WS-RDF-18-TAIL
           IF WS-R19-F029 = ZERO
               MOVE WS-R20-F016 TO WS-TAB-09-TXT(WS-IX-3)
               MOVE WS-REC-20 TO WS-REC-19
               MOVE 'Z' TO WS-R19-F011(2:1)
           ELSE
               MOVE WS-REC-19 TO WS-REC-20
               MOVE 'Z' TO WS-R20-F017(2:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0153
           END-IF.
       P0156.
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE WS-R19-F033 TO WS-RDF-18-MID
           MOVE WS-R20-F002 TO WS-RDF-18-HEAD
           MOVE SPACES TO WS-R19-G03
           IF WS-FLAG = 'Y'
               GO TO P0160
           END-IF.
       P0157.
           MOVE WS-R19-F000 TO WS-TAB-08-KEY(WS-IX-5)
           MOVE WS-R19-F020 TO WS-RDF-18-HEAD
           MOVE WS-REC-20 TO WS-REC-19
           MOVE 'P' TO WS-R19-F026.
       P0158.
           MOVE SPACES TO WS-R20-G02
           MOVE 'A' TO WS-R19-F018
           MOVE 'V' TO WS-R20-F027
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE 'Z' TO WS-R20-F025(5:1)
             WHEN 'B2'
               MOVE WS-R19-F015 TO WS-RDF-18-TAIL
               MOVE WS-REC-19 TO WS-REC-20
             WHEN 'C3'
               MOVE 'C' TO WS-R20-F031
               MOVE 'Q' TO WS-R19-F025
               MOVE WS-R19-F014 TO WS-TAB-04-KEY(WS-IX-1)
             WHEN OTHER
               MOVE 'V' TO WS-R19-F014
               MOVE 'M' TO WS-R19-F032
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0160
           END-IF.
       P0159.
           MOVE SPACES TO WS-R19-G02
           MOVE SPACES TO WS-R19-G04
           MOVE WS-R20-F027 TO WS-TAB-11-KEY(WS-IX-3)
           MOVE SPACES TO WS-R20-G00
           IF WS-R20-F024 = SPACES
               MOVE 'Z' TO WS-R19-F011(8:1)
               MOVE WS-REC-19 TO WS-REC-20
               MOVE 'Q' TO WS-R19-F010
           ELSE
               MOVE WS-R20-F031 TO WS-TAB-03-TXT(WS-IX-6)
               MOVE WS-TAB-09-KEY(WS-IX-6) TO WS-R20-F035
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0160
           END-IF.
       P0160.
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE WS-R19-F021 TO WS-RDF-18-HEAD
           MOVE ZERO TO WS-R19-F029
           MOVE 'H' TO WS-R20-F024
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R19-F034
               MOVE WS-R20-F027 TO WS-TAB-06-KEY(WS-IX-4)
               MOVE ZERO TO WS-R19-F003
             WHEN 'B2'
               MOVE 'Z' TO WS-R20-F003(5:1)
               MOVE WS-REC-20 TO WS-REC-19
               MOVE WS-REC-19 TO WS-REC-20
             WHEN 'C3'
               MOVE ZERO TO WS-R20-F007
               MOVE 'O' TO WS-R19-F017
               MOVE WS-REC-19 TO WS-REC-20
             WHEN OTHER
               MOVE ZERO TO WS-R20-F016
               MOVE WS-REC-19 TO WS-REC-20
               MOVE WS-R20-F015 TO WS-RDF-18-HEAD
           END-EVALUATE
           CONTINUE.
       P0161.
           MOVE ZERO TO WS-R21-F020
           MOVE 'Z' TO WS-R20-F005(6:1)
           MOVE WS-REC-21 TO WS-REC-20
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R21-F003(6:1)
               MOVE 'J' TO WS-R21-F026
               MOVE 'L' TO WS-R21-F028
             WHEN 'B2'
               MOVE 'X' TO WS-R21-F026
               MOVE WS-R21-F024 TO WS-RDF-18-HEAD
               MOVE WS-TAB-01-TXT(WS-IX-6) TO WS-R21-F028
             WHEN 'C3'
               MOVE WS-R21-F027 TO WS-TAB-01-KEY(WS-IX-5)
               COMPUTE WS-IX-7 = WS-IX-7 + 1
             WHEN OTHER
               MOVE 'P' TO WS-R20-F019
               MOVE SPACES TO WS-R20-G05
               COMPUTE WS-IX-7 = WS-IX-7 + 1
           END-EVALUATE.
       P0162.
           MOVE ZERO TO WS-R20-F034
           MOVE WS-REC-21 TO WS-REC-20
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'J' TO WS-R20-F013
               MOVE WS-REC-21 TO WS-REC-20
               COMPUTE WS-IX-2 = WS-IX-2 + 1
             WHEN 'B2'
               MOVE WS-REC-20 TO WS-REC-21
               MOVE ZERO TO WS-R20-F006
               COMPUTE WS-IX-7 = WS-IX-7 + 1
             WHEN 'C3'
               MOVE 'O' TO WS-R20-F032
               MOVE SPACES TO WS-R20-G01
             WHEN OTHER
               MOVE WS-REC-21 TO WS-REC-20
               MOVE WS-REC-21 TO WS-REC-20
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0168
           END-IF.
       P0163.
           MOVE SPACES TO WS-R21-G00
           MOVE WS-R20-F008 TO WS-TAB-07-KEY(WS-IX-1)
           IF WS-R20-F020 = ZERO
               MOVE ZERO TO WS-R20-F006
               MOVE 'Y' TO WS-R20-F009
           ELSE
               MOVE WS-R20-F004 TO WS-RDF-21-HEAD
               MOVE WS-TAB-02-TXT(WS-IX-1) TO WS-R21-F024
               MOVE WS-REC-21 TO WS-REC-20
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0161
           END-IF.
       P0164.
           MOVE 'B' TO WS-R21-F035
           MOVE WS-R21-F024 TO WS-RDF-21-HEAD
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R20-G00
               MOVE 'Z' TO WS-R20-F001(1:1)
             WHEN 'B2'
               MOVE WS-R20-F033 TO WS-RDF-21-TAIL
               MOVE SPACES TO WS-R20-G00
             WHEN 'C3'
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE SPACES TO WS-R20-G04
               MOVE 'Q' TO WS-R21-F028
             WHEN OTHER
               MOVE WS-REC-20 TO WS-REC-21
               MOVE 'Z' TO WS-R20-F010(1:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0168
           END-IF.
       P0165.
           MOVE 'B' TO WS-R21-F024
           MOVE WS-REC-20 TO WS-REC-21
           MOVE WS-TAB-05-TXT(WS-IX-6) TO WS-R21-F023
           IF WS-R21-F018 = ZERO
               MOVE WS-R20-F001 TO WS-TAB-09-KEY(WS-IX-7)
               MOVE 'T' TO WS-R21-F032
               MOVE 'J' TO WS-R20-F011
               MOVE WS-REC-20 TO WS-REC-21
           ELSE
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE WS-R21-F009 TO WS-TAB-07-TXT(WS-IX-3)
               MOVE WS-R20-F031 TO WS-TAB-10-TXT(WS-IX-5)
               MOVE 'Z' TO WS-R20-F003(1:1)
           END-IF.
       P0166.
           MOVE ZERO TO WS-R21-F020
           MOVE ZERO TO WS-R21-F002
           MOVE SPACES TO WS-R21-G01
           MOVE WS-R20-F013 TO WS-TAB-10-KEY(WS-IX-7)
           IF WS-FLAG = 'Y'
               GO TO P0168
           END-IF.
       P0167.
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE 'Z' TO WS-R21-F009(5:1)
           MOVE WS-REC-20 TO WS-REC-21
           IF WS-R21-F014 = SPACES
               MOVE WS-R20-F002 TO WS-RDF-18-TAIL
               MOVE ZERO TO WS-R21-F009
               COMPUTE WS-IX-2 = WS-IX-2 + 1
           ELSE
               MOVE 'W' TO WS-R21-F011
               MOVE 'U' TO WS-R20-F013
           END-IF.
       P0168.
           MOVE WS-REC-21 TO WS-REC-20
           MOVE WS-REC-21 TO WS-REC-20
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R20-G02
               MOVE 'V' TO WS-R21-F007
             WHEN 'B2'
               MOVE SPACES TO WS-R21-G00
               MOVE WS-REC-21 TO WS-REC-20
             WHEN 'C3'
               MOVE WS-REC-21 TO WS-REC-20
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               COMPUTE WS-IX-3 = WS-IX-3 + 1
             WHEN OTHER
               MOVE WS-TAB-09-TXT(WS-IX-6) TO WS-R21-F010
               MOVE 'Z' TO WS-R20-F022
           END-EVALUATE
           CONTINUE.
       P0169.
           MOVE WS-R22-F033 TO WS-TAB-02-TXT(WS-IX-7)
           MOVE 'O' TO WS-R21-F028
           MOVE ZERO TO WS-R22-F003
           MOVE 'Q' TO WS-R21-F029
           IF WS-R21-F020 = ZERO
               MOVE ZERO TO WS-R22-F012
               MOVE WS-REC-22 TO WS-REC-21
               MOVE WS-R22-F003 TO WS-RDF-21-TAIL
           ELSE
               MOVE WS-REC-22 TO WS-REC-21
               COMPUTE WS-IX-5 = WS-IX-5 + 1
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0176
           END-IF.
       P0170.
           MOVE 'Q' TO WS-R21-F026
           MOVE WS-REC-22 TO WS-REC-21
           MOVE 'Q' TO WS-R22-F001
           MOVE WS-R22-F027 TO WS-TAB-09-KEY(WS-IX-7)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R21-F005
               MOVE 'C' TO WS-R22-F029
               MOVE 'Z' TO WS-R21-F020(8:1)
             WHEN 'B2'
               MOVE 'Q' TO WS-R22-F001
               MOVE WS-R21-F032 TO WS-TAB-08-KEY(WS-IX-3)
               MOVE ZERO TO WS-R21-F009
             WHEN 'C3'
               MOVE WS-REC-22 TO WS-REC-21
               MOVE 'Z' TO WS-R22-F032(1:1)
               MOVE 'Z' TO WS-R21-F028
             WHEN OTHER
               MOVE WS-REC-21 TO WS-REC-22
               MOVE 'G' TO WS-R22-F029
               MOVE WS-REC-22 TO WS-REC-21
           END-EVALUATE.
       P0171.
           MOVE WS-R21-F031 TO WS-RDF-21-TAIL
           MOVE WS-REC-21 TO WS-REC-22
           MOVE WS-R22-F011 TO WS-RDF-21-TAIL
           IF WS-FLAG = 'Y'
               GO TO P0176
           END-IF.
       P0172.
           MOVE WS-REC-21 TO WS-REC-22
           MOVE WS-REC-22 TO WS-REC-21
           IF WS-R21-F001 = ZERO
               MOVE SPACES TO WS-R22-G04
               MOVE 'Z' TO WS-R21-F020(3:1)
               MOVE WS-TAB-05-KEY(WS-IX-2) TO WS-R22-F009
               MOVE WS-R22-F007 TO WS-TAB-10-KEY(WS-IX-2)
           ELSE
               MOVE WS-R22-F032 TO WS-TAB-04-KEY(WS-IX-7)
               MOVE 'Z' TO WS-R21-F009(10:1)
               MOVE WS-R22-F010 TO WS-RDF-21-MID
               MOVE WS-TAB-08-TXT(WS-IX-3) TO WS-R22-F020
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0176
           END-IF.
       P0173.
           MOVE WS-REC-21 TO WS-REC-22
           MOVE WS-REC-22 TO WS-REC-21
           MOVE WS-REC-22 TO WS-REC-21
           MOVE WS-TAB-11-KEY(WS-IX-0) TO WS-R22-F034
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R22-F017
               MOVE 'I' TO WS-R22-F030
               MOVE WS-REC-21 TO WS-REC-22
             WHEN 'B2'
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE WS-TAB-00-KEY(WS-IX-5) TO WS-R22-F010
               MOVE ZERO TO WS-R22-F019
             WHEN 'C3'
               MOVE 'Q' TO WS-R22-F006
               MOVE 'S' TO WS-R22-F022
               MOVE 'Z' TO WS-R22-F018(4:1)
             WHEN OTHER
               MOVE 'V' TO WS-R21-F023
               MOVE WS-R21-F031 TO WS-TAB-03-KEY(WS-IX-3)
           END-EVALUATE.
       P0174.
           MOVE 'Z' TO WS-R21-F010
           MOVE WS-REC-22 TO WS-REC-21
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE WS-TAB-05-KEY(WS-IX-7) TO WS-R22-F011
           IF WS-R21-F011 = SPACES
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'I' TO WS-R22-F029
           ELSE
               MOVE SPACES TO WS-R21-G00
               MOVE 'Z' TO WS-R22-F029(1:1)
           END-IF.
       P0175.
           MOVE WS-R21-F016 TO WS-RDF-21-HEAD
           MOVE SPACES TO WS-R22-G02
           MOVE 'Z' TO WS-R22-F004(4:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R22-F027(9:1)
               MOVE SPACES TO WS-R22-G03
             WHEN 'B2'
               MOVE 'B' TO WS-R21-F035
               MOVE WS-R22-F035 TO WS-TAB-03-TXT(WS-IX-2)
               MOVE SPACES TO WS-R21-G03
             WHEN 'C3'
               MOVE 'B' TO WS-R21-F017
               MOVE 'Z' TO WS-R22-F033(4:1)
             WHEN OTHER
               MOVE WS-REC-22 TO WS-REC-21
               MOVE WS-R22-F035 TO WS-RDF-21-TAIL
               MOVE WS-REC-21 TO WS-REC-22
           END-EVALUATE.
       P0176.
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE 'Y' TO WS-R21-F023
           MOVE WS-R21-F006 TO WS-RDF-21-TAIL
           MOVE WS-REC-21 TO WS-REC-22
           CONTINUE.
       P0177.
           MOVE WS-REC-22 TO WS-REC-23
           MOVE 'R' TO WS-R22-F014
           MOVE 'Z' TO WS-R23-F030(3:1)
           MOVE WS-REC-23 TO WS-REC-22
           IF WS-FLAG = 'Y'
               GO TO P0184
           END-IF.
       P0178.
           MOVE WS-TAB-09-KEY(WS-IX-7) TO WS-R22-F028
           MOVE SPACES TO WS-R23-G04
           MOVE WS-REC-23 TO WS-REC-22
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'S' TO WS-R23-F028
               MOVE WS-TAB-09-TXT(WS-IX-3) TO WS-R22-F033
               MOVE WS-R23-F031 TO WS-RDF-21-MID
             WHEN 'B2'
               MOVE 'Z' TO WS-R23-F022(7:1)
               MOVE 'U' TO WS-R23-F019
             WHEN 'C3'
               MOVE 'Z' TO WS-R22-F027(2:1)
               MOVE WS-R22-F012 TO WS-RDF-21-MID
               MOVE WS-REC-22 TO WS-REC-23
             WHEN OTHER
               MOVE SPACES TO WS-R23-G04
               MOVE WS-REC-23 TO WS-REC-22
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0184
           END-IF.
       P0179.
           MOVE SPACES TO WS-R22-G05
           MOVE ZERO TO WS-R22-F011
           MOVE 'D' TO WS-R23-F011
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE ZERO TO WS-R23-F023
               MOVE WS-R23-F024 TO WS-TAB-07-KEY(WS-IX-2)
             WHEN 'B2'
               MOVE 'M' TO WS-R23-F027
               MOVE WS-REC-23 TO WS-REC-22
               COMPUTE WS-IX-6 = WS-IX-6 + 1
             WHEN 'C3'
               MOVE 'Z' TO WS-R23-F027(1:1)
               MOVE SPACES TO WS-R23-G02
               MOVE WS-R22-F026 TO WS-TAB-04-KEY(WS-IX-2)
             WHEN OTHER
               MOVE SPACES TO WS-R23-G04
               MOVE 'G' TO WS-R23-F003
               COMPUTE WS-IX-7 = WS-IX-7 + 1
           END-EVALUATE.
       P0180.
           MOVE 'Z' TO WS-R22-F011(9:1)
           MOVE 'X' TO WS-R23-F034.
       P0181.
           MOVE 'W' TO WS-R22-F010
           MOVE WS-R23-F031 TO WS-TAB-02-TXT(WS-IX-1)
           IF WS-FLAG = 'Y'
               GO TO P0184
           END-IF.
       P0182.
           MOVE WS-R23-F012 TO WS-TAB-04-TXT(WS-IX-1)
           MOVE 'Z' TO WS-R22-F019(3:1)
           IF WS-FLAG = 'Y'
               GO TO P0177
           END-IF.
       P0183.
           MOVE WS-R22-F004 TO WS-RDF-21-TAIL
           MOVE WS-TAB-02-KEY(WS-IX-3) TO WS-R22-F009
           MOVE WS-REC-22 TO WS-REC-23
           MOVE WS-REC-22 TO WS-REC-23
           IF WS-R23-F009 = ZERO
               MOVE 'X' TO WS-R23-F020
               MOVE WS-REC-22 TO WS-REC-23
               MOVE WS-REC-22 TO WS-REC-23
               MOVE SPACES TO WS-R23-G00
           ELSE
               MOVE WS-TAB-05-KEY(WS-IX-0) TO WS-R23-F005
               MOVE ZERO TO WS-R22-F011
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0177
           END-IF.
       P0184.
           MOVE 'Z' TO WS-R22-F030(13:1)
           MOVE 'Z' TO WS-R22-F033(2:1)
           MOVE 'E' TO WS-R22-F002
           IF WS-R23-F033 = ZERO
               MOVE 'Q' TO WS-R23-F025
               MOVE 'Z' TO WS-R22-F009(3:1)
           ELSE
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE WS-REC-22 TO WS-REC-23
               COMPUTE WS-IX-5 = WS-IX-5 + 1
           END-IF
           CONTINUE.
       P0185.
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE 'X' TO WS-R23-F001
           MOVE 'Z' TO WS-R23-F014(17:1)
           MOVE WS-R24-F001 TO WS-RDF-24-TAIL.
       P0186.
           MOVE SPACES TO WS-R24-G01
           MOVE 'M' TO WS-R23-F014
           IF WS-R23-F002 = SPACES
               MOVE 'V' TO WS-R24-F033
               MOVE SPACES TO WS-R24-G02
               MOVE 'Z' TO WS-R24-F031(7:1)
           ELSE
               MOVE 'Z' TO WS-R24-F032(1:1)
               MOVE WS-R24-F007 TO WS-RDF-24-HEAD
               MOVE 'Q' TO WS-R23-F009
               MOVE 'Q' TO WS-R23-F023
           END-IF.
       P0187.
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE WS-R24-F023 TO WS-RDF-21-MID
           IF WS-R23-F007 = SPACES
               MOVE WS-REC-23 TO WS-REC-24
               MOVE WS-R23-F032 TO WS-TAB-06-TXT(WS-IX-2)
               MOVE 'Z' TO WS-R24-F008(1:1)
           ELSE
               MOVE WS-REC-24 TO WS-REC-23
               MOVE WS-REC-23 TO WS-REC-24
           END-IF.
       P0188.
           MOVE 'C' TO WS-R24-F031
           MOVE WS-R23-F031 TO WS-TAB-00-TXT(WS-IX-1)
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE WS-REC-23 TO WS-REC-24
           IF WS-R24-F024 = SPACES
               MOVE WS-REC-24 TO WS-REC-23
               MOVE ZERO TO WS-R23-F016
               MOVE 'Y' TO WS-R24-F004
               MOVE WS-REC-24 TO WS-REC-23
           ELSE
               MOVE WS-R24-F017 TO WS-RDF-24-TAIL
               MOVE WS-R23-F023 TO WS-TAB-10-KEY(WS-IX-1)
               MOVE 'V' TO WS-R24-F009
           END-IF.
       P0189.
           MOVE 'K' TO WS-R24-F014
           MOVE 'Z' TO WS-R24-F020(10:1)
           IF WS-R24-F000 = ZERO
               MOVE 'Z' TO WS-R24-F033(1:1)
               COMPUTE WS-IX-2 = WS-IX-2 + 1
           ELSE
               MOVE ZERO TO WS-R24-F032
               MOVE WS-R24-F027 TO WS-RDF-24-MID
               MOVE WS-REC-23 TO WS-REC-24
               MOVE WS-REC-24 TO WS-REC-23
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0192
           END-IF.
       P0190.
           MOVE WS-REC-23 TO WS-REC-24
           MOVE 'Q' TO WS-R23-F005.
       P0191.
           MOVE WS-REC-24 TO WS-REC-23
           MOVE WS-REC-24 TO WS-REC-23
           MOVE SPACES TO WS-R23-G04
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R23-F029 TO WS-TAB-04-TXT(WS-IX-7)
               MOVE SPACES TO WS-R23-G00
             WHEN 'B2'
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'R' TO WS-R24-F034
               MOVE 'Q' TO WS-R23-F027
             WHEN 'C3'
               MOVE 'V' TO WS-R24-F030
               COMPUTE WS-IX-2 = WS-IX-2 + 1
             WHEN OTHER
               MOVE 'Z' TO WS-R23-F007(8:1)
               COMPUTE WS-IX-7 = WS-IX-7 + 1
           END-EVALUATE.
       P0192.
           MOVE WS-REC-23 TO WS-REC-24
           MOVE WS-REC-24 TO WS-REC-23
           MOVE 'G' TO WS-R24-F009
           MOVE ZERO TO WS-R24-F023
           CONTINUE.
       P0193.
           MOVE 'Z' TO WS-R25-F004(3:1)
           MOVE WS-TAB-04-KEY(WS-IX-6) TO WS-R25-F030
           MOVE 'P' TO WS-R24-F018
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R25-F017
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE SPACES TO WS-R25-G01
             WHEN 'B2'
               MOVE WS-REC-25 TO WS-REC-24
               COMPUTE WS-IX-7 = WS-IX-7 + 1
             WHEN 'C3'
               MOVE SPACES TO WS-R25-G01
               MOVE ZERO TO WS-R24-F000
               MOVE ZERO TO WS-R24-F003
             WHEN OTHER
               MOVE WS-R24-F031 TO WS-TAB-04-TXT(WS-IX-4)
               MOVE WS-R24-F029 TO WS-RDF-24-TAIL
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0200
           END-IF.
       P0194.
           MOVE 'Z' TO WS-R24-F018(10:1)
           MOVE WS-REC-24 TO WS-REC-25
           MOVE SPACES TO WS-R24-G00.
       P0195.
           MOVE SPACES TO WS-R24-G00
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           IF WS-R25-F000 = ZERO
               MOVE SPACES TO WS-R24-G00
               MOVE 'D' TO WS-R25-F002
           ELSE
               MOVE ZERO TO WS-R24-F005
               MOVE WS-REC-24 TO WS-REC-25
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0200
           END-IF.
       P0196.
           MOVE 'Q' TO WS-R24-F019
           MOVE SPACES TO WS-R24-G04
           MOVE 'Y' TO WS-R24-F020
           MOVE 'Z' TO WS-R24-F003(4:1)
           IF WS-R24-F032 = ZERO
               MOVE 'A' TO WS-R25-F021
               MOVE SPACES TO WS-R25-G04
               MOVE SPACES TO WS-R25-G05
               MOVE WS-TAB-07-KEY(WS-IX-7) TO WS-R24-F004
           ELSE
               MOVE SPACES TO WS-R25-G00
               MOVE ZERO TO WS-R25-F003
               MOVE WS-R24-F028 TO WS-TAB-03-KEY(WS-IX-7)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0193
           END-IF.
       P0197.
           MOVE 'Z' TO WS-R25-F027(3:1)
           MOVE 'A' TO WS-R24-F014
           MOVE 'V' TO WS-R25-F002
           IF WS-FLAG = 'Y'
               GO TO P0200
           END-IF.
       P0198.
           MOVE WS-R24-F024 TO WS-TAB-02-KEY(WS-IX-2)
           MOVE WS-TAB-10-TXT(WS-IX-4) TO WS-R25-F026
           IF WS-R24-F011 = SPACES
               MOVE WS-REC-25 TO WS-REC-24
               MOVE 'C' TO WS-R24-F010
           ELSE
               MOVE WS-REC-25 TO WS-REC-24
               MOVE WS-TAB-02-KEY(WS-IX-3) TO WS-R25-F017
               MOVE WS-R25-F018 TO WS-RDF-24-MID
               MOVE WS-R25-F017 TO WS-TAB-00-KEY(WS-IX-1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0200
           END-IF.
       P0199.
           MOVE WS-R24-F030 TO WS-RDF-24-TAIL
           MOVE WS-REC-24 TO WS-REC-25
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R25-F011
               MOVE WS-TAB-00-KEY(WS-IX-2) TO WS-R24-F010
             WHEN 'B2'
               MOVE WS-R24-F030 TO WS-RDF-24-HEAD
               MOVE ZERO TO WS-R24-F032
               MOVE 'Z' TO WS-R25-F023(2:1)
             WHEN 'C3'
               MOVE WS-REC-25 TO WS-REC-24
               MOVE WS-TAB-02-TXT(WS-IX-1) TO WS-R25-F015
               MOVE WS-TAB-06-KEY(WS-IX-0) TO WS-R24-F025
             WHEN OTHER
               MOVE 'A' TO WS-R24-F015
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE WS-REC-25 TO WS-REC-24
           END-EVALUATE.
       P0200.
           MOVE WS-TAB-00-TXT(WS-IX-0) TO WS-R24-F024
           MOVE SPACES TO WS-R24-G00
           MOVE 'Q' TO WS-R25-F031
           IF WS-R25-F017 = SPACES
               MOVE ZERO TO WS-R24-F027
               MOVE 'Y' TO WS-R25-F006
               MOVE 'Z' TO WS-R25-F020(2:1)
               MOVE WS-R24-F009 TO WS-RDF-24-HEAD
           ELSE
               MOVE ZERO TO WS-R24-F022
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE ZERO TO WS-R25-F025
               MOVE 'Z' TO WS-R25-F021(4:1)
           END-IF
           CONTINUE.
       P0201.
           MOVE WS-REC-26 TO WS-REC-25
           MOVE WS-R26-F007 TO WS-TAB-00-TXT(WS-IX-6)
           IF WS-R26-F033 = SPACES
               MOVE 'E' TO WS-R26-F031
               MOVE 'Z' TO WS-R26-F009(7:1)
               MOVE WS-R26-F016 TO WS-RDF-24-MID
               MOVE 'Z' TO WS-R25-F004(9:1)
           ELSE
               MOVE SPACES TO WS-R26-G05
               MOVE WS-REC-25 TO WS-REC-26
           END-IF.
       P0202.
           MOVE 'H' TO WS-R25-F032
           MOVE WS-REC-26 TO WS-REC-25
           MOVE 'Z' TO WS-R25-F013(16:1)
           IF WS-R26-F017 = SPACES
               MOVE 'P' TO WS-R26-F030
               MOVE 'W' TO WS-R26-F007
               MOVE WS-R26-F026 TO WS-TAB-03-TXT(WS-IX-5)
               MOVE WS-TAB-01-KEY(WS-IX-6) TO WS-R25-F028
           ELSE
               MOVE 'Q' TO WS-R26-F015
               MOVE WS-REC-25 TO WS-REC-26
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0201
           END-IF.
       P0203.
           MOVE ZERO TO WS-R25-F034
           MOVE WS-REC-25 TO WS-REC-26
           IF WS-R26-F004 = SPACES
               MOVE WS-REC-25 TO WS-REC-26
               MOVE 'D' TO WS-R26-F005
               MOVE SPACES TO WS-R25-G00
           ELSE
               MOVE ZERO TO WS-R25-F023
               MOVE SPACES TO WS-R25-G03
               MOVE WS-R25-F012 TO WS-TAB-09-TXT(WS-IX-2)
           END-IF.
       P0204.
           MOVE WS-REC-25 TO WS-REC-26
           MOVE SPACES TO WS-R26-G01
           MOVE 'T' TO WS-R26-F023
           IF WS-FLAG = 'Y'
               GO TO P0201
           END-IF.
       P0205.
           MOVE WS-R26-F026 TO WS-RDF-24-HEAD
           MOVE WS-REC-25 TO WS-REC-26
           MOVE WS-REC-25 TO WS-REC-26
           MOVE WS-R26-F008 TO WS-RDF-24-MID
           IF WS-R25-F013 = SPACES
               MOVE WS-REC-25 TO WS-REC-26
               MOVE WS-R25-F028 TO WS-TAB-09-KEY(WS-IX-5)
               MOVE WS-TAB-07-KEY(WS-IX-7) TO WS-R25-F015
           ELSE
               MOVE 'T' TO WS-R26-F009
               MOVE 'Q' TO WS-R26-F034
               MOVE ZERO TO WS-R26-F021
           END-IF.
       P0206.
           MOVE 'M' TO WS-R25-F007
           MOVE 'G' TO WS-R25-F027
           IF WS-R25-F001 = SPACES
               MOVE WS-TAB-05-TXT(WS-IX-7) TO WS-R25-F008
               MOVE WS-TAB-02-TXT(WS-IX-7) TO WS-R25-F016
               MOVE 'Z' TO WS-R26-F031(2:1)
           ELSE
               MOVE WS-REC-25 TO WS-REC-26
               MOVE ZERO TO WS-R26-F021
               MOVE WS-REC-25 TO WS-REC-26
               MOVE ZERO TO WS-R25-F034
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0201
           END-IF.
       P0207.
           MOVE 'P' TO WS-R25-F004
           MOVE WS-R26-F034 TO WS-RDF-24-MID
           MOVE 'Z' TO WS-R25-F029(3:1)
           MOVE 'Z' TO WS-R26-F019(4:1)
           IF WS-FLAG = 'Y'
               GO TO P0208
           END-IF.
       P0208.
           MOVE WS-TAB-06-KEY(WS-IX-0) TO WS-R26-F031
           MOVE WS-REC-25 TO WS-REC-26
           MOVE 'Z' TO WS-R26-F004(13:1)
           MOVE 'L' TO WS-R25-F001
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R25-F034
               MOVE WS-R26-F024 TO WS-TAB-06-KEY(WS-IX-6)
               MOVE 'X' TO WS-R25-F012
             WHEN 'B2'
               MOVE ZERO TO WS-R25-F003
               MOVE 'J' TO WS-R25-F011
             WHEN 'C3'
               MOVE 'A' TO WS-R26-F004
               MOVE WS-REC-26 TO WS-REC-25
             WHEN OTHER
               MOVE 'I' TO WS-R25-F017
               COMPUTE WS-IX-5 = WS-IX-5 + 1
           END-EVALUATE
           CONTINUE.
       P0209.
           MOVE ZERO TO WS-R26-F018
           MOVE WS-TAB-09-TXT(WS-IX-1) TO WS-R27-F017
           MOVE 'L' TO WS-R27-F013
           MOVE 'Q' TO WS-R26-F002
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-26 TO WS-REC-27
               MOVE 'Q' TO WS-R27-F027
               MOVE WS-R27-F023 TO WS-RDF-24-HEAD
             WHEN 'B2'
               MOVE 'P' TO WS-R27-F000
               MOVE 'L' TO WS-R26-F005
               MOVE WS-REC-27 TO WS-REC-26
             WHEN 'C3'
               MOVE ZERO TO WS-R26-F021
               MOVE 'C' TO WS-R27-F031
               MOVE 'Q' TO WS-R26-F002
             WHEN OTHER
               MOVE 'E' TO WS-R27-F025
               MOVE SPACES TO WS-R26-G02
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0216
           END-IF.
       P0210.
           MOVE WS-R26-F016 TO WS-RDF-27-TAIL
           MOVE WS-REC-26 TO WS-REC-27
           MOVE SPACES TO WS-R26-G01
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           IF WS-FLAG = 'Y'
               GO TO P0209
           END-IF.
       P0211.
           MOVE WS-TAB-05-TXT(WS-IX-5) TO WS-R26-F000
           MOVE WS-R27-F006 TO WS-RDF-27-MID
           MOVE ZERO TO WS-R27-F014
           IF WS-FLAG = 'Y'
               GO TO P0216
           END-IF.
       P0212.
           MOVE 'Z' TO WS-R27-F003
           MOVE WS-R26-F012 TO WS-TAB-07-TXT(WS-IX-3)
           MOVE 'Z' TO WS-R27-F010(6:1)
           MOVE 'Z' TO WS-R26-F018(9:1)
           IF WS-R27-F013 = SPACES
               MOVE ZERO TO WS-R26-F000
               MOVE SPACES TO WS-R26-G02
               MOVE 'W' TO WS-R26-F002
           ELSE
               MOVE WS-R27-F026 TO WS-TAB-00-KEY(WS-IX-5)
               MOVE 'Z' TO WS-R27-F025(9:1)
               MOVE SPACES TO WS-R27-G03
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0216
           END-IF.
       P0213.
           MOVE WS-R27-F006 TO WS-TAB-11-KEY(WS-IX-7)
           MOVE 'Z' TO WS-R27-F012(1:1)
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE 'N' TO WS-R27-F008
           IF WS-FLAG = 'Y'
               GO TO P0216
           END-IF.
       P0214.
           MOVE SPACES TO WS-R27-G05
           MOVE 'Y' TO WS-R26-F005
           MOVE 'G' TO WS-R26-F015
           MOVE WS-TAB-02-TXT(WS-IX-3) TO WS-R27-F027.
       P0215.
           MOVE WS-R26-F022 TO WS-RDF-24-TAIL
           MOVE 'M' TO WS-R26-F005
           MOVE 'Z' TO WS-R27-F005(2:1)
           IF WS-R26-F024 = ZERO
               MOVE 'Z' TO WS-R26-F013(3:1)
               MOVE 'A' TO WS-R27-F003
               MOVE 'Z' TO WS-R26-F028(7:1)
           ELSE
               MOVE WS-R26-F031 TO WS-RDF-27-MID
               MOVE 'J' TO WS-R27-F017
               MOVE 'E' TO WS-R27-F007
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0216
           END-IF.
       P0216.
           MOVE SPACES TO WS-R26-G04
           MOVE 'Q' TO WS-R27-F002
           CONTINUE.
       P0217.
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE WS-TAB-01-KEY(WS-IX-7) TO WS-R27-F023
           MOVE 'Z' TO WS-R27-F035(6:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R27-F024 TO WS-TAB-09-TXT(WS-IX-5)
               MOVE WS-REC-28 TO WS-REC-27
               MOVE WS-REC-28 TO WS-REC-27
             WHEN 'B2'
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE WS-REC-27 TO WS-REC-28
               MOVE WS-R27-F027 TO WS-RDF-27-MID
             WHEN 'C3'
               MOVE SPACES TO WS-R27-G00
               MOVE WS-R28-F004 TO WS-TAB-04-KEY(WS-IX-4)
               MOVE WS-REC-27 TO WS-REC-28
             WHEN OTHER
               MOVE WS-R28-F001 TO WS-TAB-08-KEY(WS-IX-2)
               MOVE WS-REC-27 TO WS-REC-28
               MOVE ZERO TO WS-R28-F006
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0224
           END-IF.
       P0218.
           MOVE WS-REC-28 TO WS-REC-27
           MOVE 'Q' TO WS-R27-F011
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R28-F015 TO WS-RDF-27-MID
               MOVE 'Z' TO WS-R28-F008(3:1)
               MOVE 'G' TO WS-R28-F015
             WHEN 'B2'
               MOVE 'D' TO WS-R27-F031
               MOVE 'Z' TO WS-R27-F024(4:1)
             WHEN 'C3'
               MOVE 'Z' TO WS-R27-F028(8:1)
               MOVE 'K' TO WS-R28-F002
               MOVE WS-R28-F022 TO WS-RDF-27-MID
             WHEN OTHER
               MOVE SPACES TO WS-R28-G04
               MOVE WS-REC-27 TO WS-REC-28
               MOVE WS-R27-F033 TO WS-TAB-11-TXT(WS-IX-7)
           END-EVALUATE.
       P0219.
           MOVE WS-R27-F012 TO WS-RDF-27-HEAD
           MOVE WS-R28-F016 TO WS-RDF-27-MID
           IF WS-FLAG = 'Y'
               GO TO P0224
           END-IF.
       P0220.
           MOVE WS-REC-27 TO WS-REC-28
           MOVE 'R' TO WS-R27-F006
           MOVE 'Q' TO WS-R27-F002
           MOVE ZERO TO WS-R27-F024
           IF WS-FLAG = 'Y'
               GO TO P0217
           END-IF.
       P0221.
           MOVE WS-R27-F007 TO WS-TAB-11-KEY(WS-IX-3)
           MOVE SPACES TO WS-R28-G01
           MOVE WS-R27-F022 TO WS-TAB-01-TXT(WS-IX-2)
           MOVE WS-REC-28 TO WS-REC-27
           IF WS-FLAG = 'Y'
               GO TO P0224
           END-IF.
       P0222.
           MOVE WS-R28-F029 TO WS-RDF-27-HEAD
           COMPUTE WS-IX-5 = WS-IX-5 + 1.
       P0223.
           MOVE 'Z' TO WS-R28-F025(1:1)
           MOVE 'Z' TO WS-R27-F014(6:1)
           IF WS-R28-F019 = SPACES
               MOVE WS-R27-F032 TO WS-TAB-06-KEY(WS-IX-0)
               MOVE SPACES TO WS-R27-G01
               MOVE 'V' TO WS-R28-F009
           ELSE
               MOVE 'Z' TO WS-R28-F019(17:1)
               MOVE WS-REC-28 TO WS-REC-27
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0224
           END-IF.
       P0224.
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE 'Z' TO WS-R28-F001(1:1)
           MOVE 'Z' TO WS-R27-F017(1:1)
           IF WS-R28-F000 = ZERO
               MOVE WS-REC-28 TO WS-REC-27
               MOVE WS-R27-F014 TO WS-RDF-27-TAIL
               MOVE WS-R28-F014 TO WS-TAB-10-KEY(WS-IX-0)
           ELSE
               MOVE 'R' TO WS-R28-F003
               MOVE WS-TAB-05-KEY(WS-IX-6) TO WS-R28-F017
           END-IF
           CONTINUE.
       P0225.
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE SPACES TO WS-R29-G04
           MOVE 'B' TO WS-R29-F005
           MOVE WS-REC-29 TO WS-REC-28
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R28-G02
               MOVE SPACES TO WS-R28-G02
               COMPUTE WS-IX-4 = WS-IX-4 + 1
             WHEN 'B2'
               MOVE 'Z' TO WS-R29-F022(1:1)
               MOVE ZERO TO WS-R29-F025
               MOVE 'X' TO WS-R28-F025
             WHEN 'C3'
               MOVE WS-REC-28 TO WS-REC-29
               MOVE 'Z' TO WS-R28-F014(3:1)
               MOVE 'Z' TO WS-R29-F008(3:1)
             WHEN OTHER
               MOVE ZERO TO WS-R29-F032
               MOVE WS-REC-28 TO WS-REC-29
           END-EVALUATE.
       P0226.
           MOVE 'Z' TO WS-R28-F025(2:1)
           MOVE 'Z' TO WS-R28-F021(2:1)
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE 'Q' TO WS-R29-F018
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R29-F010(1:1)
               MOVE SPACES TO WS-R29-G01
               MOVE 'Z' TO WS-R28-F012(6:1)
             WHEN 'B2'
               MOVE WS-REC-29 TO WS-REC-28
               MOVE SPACES TO WS-R28-G01
               MOVE WS-R28-F023 TO WS-TAB-08-TXT(WS-IX-6)
             WHEN 'C3'
               MOVE ZERO TO WS-R28-F006
               MOVE 'Z' TO WS-R29-F029(14:1)
               MOVE WS-R29-F022 TO WS-RDF-27-TAIL
             WHEN OTHER
               MOVE 'P' TO WS-R29-F021
               MOVE WS-REC-28 TO WS-REC-29
               MOVE WS-R28-F018 TO WS-TAB-03-KEY(WS-IX-5)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0225
           END-IF.
       P0227.
           MOVE WS-REC-28 TO WS-REC-29
           MOVE SPACES TO WS-R28-G04
           MOVE WS-REC-29 TO WS-REC-28
           MOVE SPACES TO WS-R29-G00
           IF WS-R28-F001 = ZERO
               MOVE 'Z' TO WS-R29-F007
               MOVE 'F' TO WS-R28-F012
               COMPUTE WS-IX-4 = WS-IX-4 + 1
           ELSE
               MOVE SPACES TO WS-R28-G02
               MOVE 'Z' TO WS-R29-F023(4:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0232
           END-IF.
       P0228.
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE 'N' TO WS-R29-F023.
       P0229.
           MOVE 'Z' TO WS-R28-F006(4:1)
           MOVE WS-TAB-02-KEY(WS-IX-4) TO WS-R29-F004
           COMPUTE WS-IX-5 = WS-IX-5 + 1
           MOVE ZERO TO WS-R29-F006
           IF WS-FLAG = 'Y'
               GO TO P0232
           END-IF.
       P0230.
           MOVE 'F' TO WS-R28-F018
           MOVE SPACES TO WS-R28-G00
           IF WS-R29-F026 = ZERO
               MOVE 'Q' TO WS-R28-F010
               MOVE WS-REC-28 TO WS-REC-29
               MOVE SPACES TO WS-R28-G03
               MOVE ZERO TO WS-R29-F026
           ELSE
               MOVE WS-R29-F009 TO WS-RDF-27-MID
               MOVE WS-R29-F006 TO WS-RDF-27-MID
           END-IF.
       P0231.
           MOVE WS-R28-F013 TO WS-TAB-01-KEY(WS-IX-4)
           MOVE 'W' TO WS-R29-F015
           MOVE 'W' TO WS-R28-F012
           MOVE WS-TAB-09-TXT(WS-IX-1) TO WS-R28-F002
           IF WS-R28-F024 = SPACES
               MOVE ZERO TO WS-R28-F028
               MOVE WS-R28-F027 TO WS-TAB-03-KEY(WS-IX-6)
           ELSE
               MOVE 'O' TO WS-R28-F032
               MOVE 'S' TO WS-R29-F017
               MOVE 'Z' TO WS-R29-F000(2:1)
               MOVE 'Y' TO WS-R28-F030
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0232
           END-IF.
       P0232.
           MOVE SPACES TO WS-R28-G02
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE ZERO TO WS-R29-F013
           MOVE WS-REC-29 TO WS-REC-28
           CONTINUE.
       P0233.
           MOVE WS-REC-29 TO WS-REC-30
           MOVE WS-TAB-08-KEY(WS-IX-3) TO WS-R30-F016
           IF WS-FLAG = 'Y'
               GO TO P0240
           END-IF.
       P0234.
           MOVE 'Q' TO WS-R30-F008
           MOVE 'S' TO WS-R30-F005
           MOVE 'Z' TO WS-R29-F030(10:1)
           MOVE SPACES TO WS-R30-G05
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-30 TO WS-REC-29
               MOVE 'Q' TO WS-R30-F002
               MOVE 'Q' TO WS-R29-F034
             WHEN 'B2'
               MOVE 'N' TO WS-R30-F025
               MOVE ZERO TO WS-R29-F008
               MOVE 'I' TO WS-R29-F022
             WHEN 'C3'
               MOVE ZERO TO WS-R29-F003
               MOVE WS-R30-F015 TO WS-RDF-27-TAIL
               MOVE 'Z' TO WS-R30-F028(1:1)
             WHEN OTHER
               MOVE ZERO TO WS-R30-F032
               MOVE 'E' TO WS-R29-F005
               MOVE SPACES TO WS-R30-G04
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0240
           END-IF.
       P0235.
           MOVE 'V' TO WS-R30-F020
           MOVE WS-TAB-01-KEY(WS-IX-0) TO WS-R30-F018
           MOVE WS-REC-29 TO WS-REC-30
           IF WS-FLAG = 'Y'
               GO TO P0233
           END-IF.
       P0236.
           MOVE 'Q' TO WS-R29-F032
           MOVE WS-REC-30 TO WS-REC-29
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R29-G02
               MOVE 'X' TO WS-R30-F014
             WHEN 'B2'
               MOVE WS-REC-29 TO WS-REC-30
               MOVE SPACES TO WS-R30-G02
               MOVE WS-REC-30 TO WS-REC-29
             WHEN 'C3'
               MOVE 'T' TO WS-R29-F030
               MOVE 'Z' TO WS-R30-F020(3:1)
               MOVE SPACES TO WS-R30-G04
             WHEN OTHER
               MOVE 'N' TO WS-R29-F022
               MOVE 'Q' TO WS-R30-F010
               MOVE WS-R29-F025 TO WS-RDF-30-MID
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0240
           END-IF.
       P0237.
           MOVE WS-REC-29 TO WS-REC-30
           MOVE 'Q' TO WS-R29-F029
           IF WS-R30-F005 = SPACES
               MOVE WS-R29-F006 TO WS-TAB-10-TXT(WS-IX-1)
               MOVE WS-REC-30 TO WS-REC-29
               MOVE 'L' TO WS-R29-F005
               COMPUTE WS-IX-5 = WS-IX-5 + 1
           ELSE
               MOVE 'Z' TO WS-R30-F018(3:1)
               MOVE WS-REC-30 TO WS-REC-29
               MOVE 'J' TO WS-R30-F009
               MOVE ZERO TO WS-R30-F016
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0233
           END-IF.
       P0238.
           MOVE WS-TAB-07-KEY(WS-IX-7) TO WS-R30-F001
           MOVE 'Z' TO WS-R30-F025(1:1)
           MOVE 'Q' TO WS-R30-F024
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-TAB-04-KEY(WS-IX-3) TO WS-R30-F019
               MOVE WS-TAB-06-KEY(WS-IX-4) TO WS-R29-F029
             WHEN 'B2'
               MOVE WS-TAB-04-KEY(WS-IX-7) TO WS-R29-F021
               MOVE WS-REC-30 TO WS-REC-29
               MOVE WS-REC-29 TO WS-REC-30
             WHEN 'C3'
               MOVE 'Z' TO WS-R29-F010(4:1)
               MOVE 'Z' TO WS-R29-F001(3:1)
               MOVE 'E' TO WS-R30-F023
             WHEN OTHER
               MOVE 'Z' TO WS-R30-F018(6:1)
               MOVE SPACES TO WS-R29-G01
               COMPUTE WS-IX-0 = WS-IX-0 + 1
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0233
           END-IF.
       P0239.
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           MOVE WS-TAB-08-KEY(WS-IX-6) TO WS-R29-F021
           MOVE 'D' TO WS-R30-F020
           IF WS-R30-F023 = SPACES
               MOVE WS-R29-F028 TO WS-TAB-05-KEY(WS-IX-5)
               MOVE WS-R29-F024 TO WS-TAB-07-TXT(WS-IX-3)
           ELSE
               MOVE WS-R29-F017 TO WS-TAB-11-KEY(WS-IX-1)
               MOVE WS-REC-29 TO WS-REC-30
               MOVE WS-REC-30 TO WS-REC-29
               MOVE 'O' TO WS-R29-F007
           END-IF.
       P0240.
           MOVE WS-TAB-10-TXT(WS-IX-1) TO WS-R30-F022
           MOVE 'Z' TO WS-R29-F017
           MOVE WS-R30-F019 TO WS-RDF-30-TAIL
           MOVE 'Q' TO WS-R30-F027
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R30-F019 TO WS-RDF-30-MID
               MOVE WS-R30-F000 TO WS-RDF-27-HEAD
               MOVE 'J' TO WS-R29-F029
             WHEN 'B2'
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE 'K' TO WS-R29-F031
               MOVE WS-R29-F020 TO WS-TAB-05-TXT(WS-IX-4)
             WHEN 'C3'
               MOVE WS-R30-F015 TO WS-RDF-30-TAIL
               MOVE 'N' TO WS-R30-F014
               MOVE WS-TAB-05-TXT(WS-IX-2) TO WS-R30-F032
             WHEN OTHER
               MOVE 'E' TO WS-R29-F029
               MOVE WS-TAB-06-TXT(WS-IX-7) TO WS-R29-F016
               MOVE WS-R30-F030 TO WS-RDF-27-MID
           END-EVALUATE
           CONTINUE.
       P0241.
           MOVE 'X' TO WS-R31-F006
           MOVE 'Q' TO WS-R31-F013
           MOVE SPACES TO WS-R31-G02
           MOVE 'O' TO WS-R30-F001
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R30-G00
               MOVE 'Z' TO WS-R31-F032(1:1)
               MOVE WS-R31-F004 TO WS-TAB-07-KEY(WS-IX-6)
             WHEN 'B2'
               MOVE 'O' TO WS-R30-F027
               MOVE 'Z' TO WS-R31-F030(1:1)
               MOVE WS-TAB-08-TXT(WS-IX-5) TO WS-R31-F032
             WHEN 'C3'
               MOVE 'Q' TO WS-R31-F035
               MOVE WS-REC-30 TO WS-REC-31
             WHEN OTHER
               MOVE 'Z' TO WS-R31-F000(5:1)
               MOVE WS-REC-30 TO WS-REC-31
               MOVE WS-REC-31 TO WS-REC-30
           END-EVALUATE.
       P0242.
           MOVE WS-R30-F008 TO WS-TAB-02-KEY(WS-IX-6)
           MOVE 'Q' TO WS-R31-F015.
       P0243.
           MOVE 'Z' TO WS-R30-F023(2:1)
           MOVE ZERO TO WS-R30-F029
           MOVE 'Z' TO WS-R30-F030(8:1)
           IF WS-R30-F017 = ZERO
               MOVE 'Z' TO WS-R31-F025(2:1)
               MOVE 'T' TO WS-R30-F026
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'Z' TO WS-R31-F035(7:1)
           ELSE
               MOVE WS-R30-F013 TO WS-RDF-30-MID
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'Z' TO WS-R30-F031(2:1)
               MOVE WS-REC-31 TO WS-REC-30
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0248
           END-IF.
       P0244.
           MOVE 'I' TO WS-R31-F015
           MOVE ZERO TO WS-R31-F025
           MOVE SPACES TO WS-R30-G00
           IF WS-R31-F005 = SPACES
               MOVE WS-R31-F015 TO WS-RDF-30-MID
               MOVE WS-REC-30 TO WS-REC-31
               MOVE WS-R31-F017 TO WS-TAB-11-KEY(WS-IX-4)
           ELSE
               MOVE SPACES TO WS-R31-G01
               MOVE 'Z' TO WS-R30-F028(8:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0241
           END-IF.
       P0245.
           MOVE SPACES TO WS-R30-G04
           MOVE ZERO TO WS-R31-F022
           IF WS-R30-F007 = SPACES
               MOVE ZERO TO WS-R31-F022
               MOVE 'L' TO WS-R30-F005
           ELSE
               MOVE 'Y' TO WS-R30-F015
               MOVE 'A' TO WS-R30-F019
               COMPUTE WS-IX-2 = WS-IX-2 + 1
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0241
           END-IF.
       P0246.
           MOVE WS-REC-30 TO WS-REC-31
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE 'K' TO WS-R31-F019
           MOVE WS-REC-31 TO WS-REC-30
           IF WS-R31-F000 = SPACES
               MOVE WS-TAB-10-KEY(WS-IX-2) TO WS-R31-F018
               MOVE 'Q' TO WS-R30-F031
           ELSE
               MOVE 'Q' TO WS-R31-F034
               MOVE WS-REC-31 TO WS-REC-30
           END-IF.
       P0247.
           MOVE SPACES TO WS-R31-G02
           MOVE ZERO TO WS-R30-F016
           MOVE 'Z' TO WS-R31-F001(1:1)
           IF WS-FLAG = 'Y'
               GO TO P0241
           END-IF.
       P0248.
           MOVE 'Q' TO WS-R31-F017
           COMPUTE WS-IX-5 = WS-IX-5 + 1
           CONTINUE.
       P0249.
           MOVE WS-REC-31 TO WS-REC-32
           MOVE WS-R31-F018 TO WS-RDF-30-MID
           MOVE 'Q' TO WS-R32-F027
           MOVE 'Z' TO WS-R32-F001(3:1)
           IF WS-R32-F016 = SPACES
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE WS-TAB-08-KEY(WS-IX-4) TO WS-R32-F019
               MOVE WS-REC-32 TO WS-REC-31
               MOVE ZERO TO WS-R31-F002
           ELSE
               MOVE 'N' TO WS-R32-F033
               MOVE WS-TAB-03-KEY(WS-IX-0) TO WS-R32-F019
               MOVE SPACES TO WS-R32-G01
               MOVE 'Y' TO WS-R32-F033
           END-IF.
       P0250.
           MOVE WS-REC-31 TO WS-REC-32
           MOVE 'Z' TO WS-R32-F012(10:1)
           MOVE SPACES TO WS-R31-G05
           IF WS-R31-F005 = SPACES
               MOVE 'Q' TO WS-R32-F014
               MOVE WS-R32-F010 TO WS-RDF-30-MID
               MOVE 'I' TO WS-R32-F026
           ELSE
               MOVE 'O' TO WS-R31-F024
               MOVE 'Z' TO WS-R31-F001(2:1)
               MOVE 'Q' TO WS-R31-F011
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0249
           END-IF.
       P0251.
           MOVE WS-REC-31 TO WS-REC-32
           MOVE WS-REC-32 TO WS-REC-31
           MOVE 'Z' TO WS-R32-F018(4:1)
           MOVE WS-R31-F011 TO WS-TAB-04-KEY(WS-IX-7).
       P0252.
           MOVE 'I' TO WS-R31-F014
           MOVE SPACES TO WS-R31-G03
           MOVE 'Z' TO WS-R32-F007(4:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'I' TO WS-R31-F035
               MOVE SPACES TO WS-R31-G04
             WHEN 'B2'
               MOVE 'R' TO WS-R31-F000
               MOVE WS-REC-32 TO WS-REC-31
               MOVE WS-R32-F020 TO WS-RDF-30-TAIL
             WHEN 'C3'
               MOVE 'Y' TO WS-R32-F001
               MOVE 'Z' TO WS-R32-F000(2:1)
               MOVE 'I' TO WS-R31-F013
             WHEN OTHER
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE WS-REC-31 TO WS-REC-32
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0249
           END-IF.
       P0253.
           MOVE 'R' TO WS-R31-F001
           MOVE ZERO TO WS-R32-F022
           MOVE WS-R32-F011 TO WS-RDF-30-MID
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R31-F028 TO WS-TAB-01-TXT(WS-IX-2)
               MOVE ZERO TO WS-R32-F006
               MOVE WS-REC-32 TO WS-REC-31
             WHEN 'B2'
               MOVE SPACES TO WS-R32-G02
               MOVE ZERO TO WS-R31-F018
               MOVE WS-R32-F004 TO WS-RDF-30-MID
             WHEN 'C3'
               MOVE 'Q' TO WS-R31-F029
               MOVE WS-REC-31 TO WS-REC-32
               MOVE 'J' TO WS-R31-F035
             WHEN OTHER
               MOVE ZERO TO WS-R32-F017
               MOVE WS-TAB-07-TXT(WS-IX-6) TO WS-R31-F001
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0256
           END-IF.
       P0254.
           MOVE WS-REC-31 TO WS-REC-32
           MOVE WS-REC-32 TO WS-REC-31
           MOVE WS-REC-32 TO WS-REC-31
           IF WS-R31-F014 = SPACES
               MOVE 'Z' TO WS-R31-F002(2:1)
               MOVE WS-R31-F015 TO WS-RDF-30-TAIL
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE SPACES TO WS-R32-G02
           ELSE
               MOVE 'D' TO WS-R32-F021
               MOVE WS-R31-F006 TO WS-TAB-10-TXT(WS-IX-6)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0256
           END-IF.
       P0255.
           MOVE WS-R31-F028 TO WS-RDF-30-HEAD
           MOVE SPACES TO WS-R31-G04
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE 'Z' TO WS-R32-F008
             WHEN 'B2'
               MOVE 'C' TO WS-R32-F035
               MOVE SPACES TO WS-R31-G04
               MOVE 'Z' TO WS-R31-F000(5:1)
             WHEN 'C3'
               MOVE 'N' TO WS-R32-F026
               MOVE SPACES TO WS-R31-G05
               MOVE ZERO TO WS-R32-F034
             WHEN OTHER
               MOVE WS-R32-F009 TO WS-RDF-30-MID
               MOVE WS-REC-32 TO WS-REC-31
               MOVE SPACES TO WS-R32-G03
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0249
           END-IF.
       P0256.
           MOVE WS-REC-31 TO WS-REC-32
           MOVE WS-R31-F021 TO WS-TAB-00-TXT(WS-IX-0)
           MOVE WS-REC-31 TO WS-REC-32
           IF WS-R31-F017 = SPACES
               MOVE 'W' TO WS-R32-F021
               MOVE 'Q' TO WS-R31-F016
               MOVE 'Q' TO WS-R32-F014
               MOVE ZERO TO WS-R32-F006
           ELSE
               MOVE ZERO TO WS-R32-F017
               MOVE WS-R31-F033 TO WS-TAB-06-TXT(WS-IX-3)
               MOVE WS-REC-32 TO WS-REC-31
           END-IF
           CONTINUE.
       P0257.
           MOVE 'P' TO WS-R33-F014
           MOVE 'F' TO WS-R32-F005
           IF WS-R33-F031 = SPACES
               MOVE WS-REC-32 TO WS-REC-33
               MOVE 'T' TO WS-R33-F017
           ELSE
               MOVE 'K' TO WS-R32-F020
               MOVE 'Z' TO WS-R33-F002(5:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0264
           END-IF.
       P0258.
           MOVE WS-REC-32 TO WS-REC-33
           MOVE WS-R33-F013 TO WS-TAB-01-KEY(WS-IX-4)
           IF WS-FLAG = 'Y'
               GO TO P0264
           END-IF.
       P0259.
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE 'Q' TO WS-R33-F019
           MOVE SPACES TO WS-R33-G02
           MOVE 'Z' TO WS-R32-F021(7:1)
           IF WS-FLAG = 'Y'
               GO TO P0264
           END-IF.
       P0260.
           MOVE WS-R32-F021 TO WS-RDF-33-TAIL
           MOVE WS-R33-F027 TO WS-TAB-10-KEY(WS-IX-7)
           MOVE WS-R33-F003 TO WS-RDF-30-MID
           IF WS-R32-F030 = SPACES
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE WS-R33-F026 TO WS-RDF-30-HEAD
               MOVE WS-TAB-01-TXT(WS-IX-1) TO WS-R32-F029
           ELSE
               MOVE 'O' TO WS-R33-F033
               MOVE 'Q' TO WS-R32-F023
           END-IF.
       P0261.
           MOVE WS-REC-33 TO WS-REC-32
           MOVE 'P' TO WS-R32-F016.
       P0262.
           MOVE SPACES TO WS-R33-G04
           MOVE WS-R33-F006 TO WS-TAB-01-TXT(WS-IX-1)
           IF WS-R33-F019 = SPACES
               MOVE 'Z' TO WS-R33-F002(7:1)
               MOVE WS-TAB-02-TXT(WS-IX-1) TO WS-R33-F002
               MOVE 'Z' TO WS-R33-F023(2:1)
               MOVE 'Q' TO WS-R33-F000
           ELSE
               MOVE ZERO TO WS-R33-F030
               MOVE WS-TAB-04-KEY(WS-IX-6) TO WS-R33-F014
           END-IF.
       P0263.
           MOVE 'Z' TO WS-R32-F005(6:1)
           MOVE 'E' TO WS-R33-F014
           MOVE WS-REC-33 TO WS-REC-32
           IF WS-R32-F035 = SPACES
               MOVE WS-R32-F020 TO WS-TAB-10-KEY(WS-IX-6)
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE ZERO TO WS-R32-F014
           ELSE
               MOVE WS-REC-32 TO WS-REC-33
               MOVE SPACES TO WS-R32-G03
               MOVE 'Q' TO WS-R32-F027
               MOVE 'Z' TO WS-R32-F030(2:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0264
           END-IF.
       P0264.
           MOVE 'J' TO WS-R32-F026
           MOVE 'Q' TO WS-R33-F003
           MOVE 'V' TO WS-R33-F013
           IF WS-R33-F021 = SPACES
               MOVE ZERO TO WS-R33-F015
               MOVE 'Q' TO WS-R33-F019
               MOVE WS-TAB-07-KEY(WS-IX-6) TO WS-R32-F028
           ELSE
               MOVE 'Q' TO WS-R33-F029
               MOVE WS-REC-33 TO WS-REC-32
               MOVE SPACES TO WS-R33-G02
           END-IF
           CONTINUE.
       P0265.
           MOVE WS-REC-34 TO WS-REC-33
           MOVE 'O' TO WS-R33-F010
           MOVE SPACES TO WS-R34-G05
           MOVE SPACES TO WS-R34-G03
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R34-F006(6:1)
               MOVE WS-R34-F019 TO WS-RDF-33-MID
               MOVE ZERO TO WS-R34-F021
             WHEN 'B2'
               MOVE WS-REC-34 TO WS-REC-33
               MOVE 'Z' TO WS-R34-F017(4:1)
               MOVE 'M' TO WS-R34-F032
             WHEN 'C3'
               MOVE ZERO TO WS-R34-F007
               MOVE ZERO TO WS-R33-F008
               MOVE WS-R34-F015 TO WS-TAB-00-TXT(WS-IX-4)
             WHEN OTHER
               MOVE 'Z' TO WS-R34-F032(3:1)
               MOVE WS-R34-F008 TO WS-RDF-33-MID
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0272
           END-IF.
       P0266.
           MOVE WS-R34-F014 TO WS-TAB-08-TXT(WS-IX-2)
           MOVE WS-REC-34 TO WS-REC-33.
       P0267.
           MOVE ZERO TO WS-R33-F015
           MOVE 'Q' TO WS-R34-F023
           MOVE 'L' TO WS-R33-F029
           MOVE 'G' TO WS-R33-F034
           IF WS-FLAG = 'Y'
               GO TO P0272
           END-IF.
       P0268.
           MOVE 'Z' TO WS-R34-F020(2:1)
           MOVE WS-REC-33 TO WS-REC-34
           MOVE ZERO TO WS-R33-F018
           MOVE WS-REC-33 TO WS-REC-34
           IF WS-R34-F007 = ZERO
               MOVE WS-REC-33 TO WS-REC-34
               MOVE SPACES TO WS-R34-G05
               MOVE WS-REC-34 TO WS-REC-33
               MOVE 'S' TO WS-R33-F031
           ELSE
               MOVE 'H' TO WS-R34-F003
               MOVE WS-R34-F001 TO WS-RDF-33-HEAD
               MOVE ZERO TO WS-R34-F021
               MOVE 'A' TO WS-R34-F032
           END-IF.
       P0269.
           MOVE WS-R33-F005 TO WS-TAB-06-KEY(WS-IX-2)
           MOVE SPACES TO WS-R33-G00
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           IF WS-R34-F001 = SPACES
               MOVE 'S' TO WS-R33-F026
               MOVE 'Z' TO WS-R33-F000
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'G' TO WS-R33-F033
           ELSE
               MOVE 'U' TO WS-R33-F033
               MOVE ZERO TO WS-R33-F015
               MOVE WS-R34-F034 TO WS-TAB-01-TXT(WS-IX-7)
               MOVE 'N' TO WS-R34-F029
           END-IF.
       P0270.
           MOVE 'E' TO WS-R34-F005
           MOVE 'P' TO WS-R33-F010
           IF WS-R34-F003 = SPACES
               MOVE WS-REC-33 TO WS-REC-34
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE WS-REC-33 TO WS-REC-34
           ELSE
               MOVE 'C' TO WS-R33-F021
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE WS-R33-F022 TO WS-TAB-11-TXT(WS-IX-2)
           END-IF.
       P0271.
           MOVE WS-R33-F034 TO WS-TAB-01-TXT(WS-IX-1)
           MOVE WS-R33-F008 TO WS-RDF-33-MID
           IF WS-R34-F012 = ZERO
               MOVE 'V' TO WS-R33-F029
               MOVE 'Y' TO WS-R34-F018
               MOVE 'O' TO WS-R33-F019
           ELSE
               MOVE 'Z' TO WS-R33-F032
               MOVE ZERO TO WS-R33-F011
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE WS-REC-33 TO WS-REC-34
           END-IF.
       P0272.
           MOVE 'S' TO WS-R34-F019
           MOVE 'W' TO WS-R33-F029
           MOVE WS-R34-F018 TO WS-RDF-33-HEAD
           IF WS-R33-F031 = SPACES
               MOVE 'Q' TO WS-R34-F011
               MOVE SPACES TO WS-R33-G00
           ELSE
               MOVE ZERO TO WS-R34-F025
               MOVE SPACES TO WS-R33-G00
               MOVE 'Z' TO WS-R33-F017(7:1)
               MOVE 'Q' TO WS-R34-F027
           END-IF
           CONTINUE.
       P0273.
           MOVE WS-R35-F011 TO WS-RDF-33-MID
           COMPUTE WS-IX-1 = WS-IX-1 + 1
           MOVE WS-R34-F016 TO WS-RDF-33-MID
           MOVE WS-R35-F026 TO WS-RDF-33-MID
           IF WS-FLAG = 'Y'
               GO TO P0280
           END-IF.
       P0274.
           MOVE 'E' TO WS-R35-F024
           MOVE SPACES TO WS-R35-G04
           MOVE WS-TAB-01-TXT(WS-IX-5) TO WS-R35-F023
           MOVE ZERO TO WS-R35-F011.
       P0275.
           MOVE 'Z' TO WS-R34-F008(14:1)
           MOVE ZERO TO WS-R35-F013
           MOVE SPACES TO WS-R34-G01.
       P0276.
           MOVE 'Z' TO WS-R34-F032(1:1)
           MOVE WS-R34-F021 TO WS-RDF-33-MID
           IF WS-R35-F020 = SPACES
               MOVE 'N' TO WS-R34-F027
               MOVE 'Z' TO WS-R34-F012(1:1)
               MOVE 'J' TO WS-R35-F028
               MOVE WS-REC-35 TO WS-REC-34
           ELSE
               MOVE WS-REC-35 TO WS-REC-34
               MOVE WS-REC-35 TO WS-REC-34
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0280
           END-IF.
       P0277.
           MOVE WS-REC-35 TO WS-REC-34
           MOVE 'Z' TO WS-R34-F024(5:1)
           MOVE SPACES TO WS-R34-G03
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-35 TO WS-REC-34
               MOVE WS-REC-34 TO WS-REC-35
               MOVE ZERO TO WS-R35-F025
             WHEN 'B2'
               MOVE 'Z' TO WS-R35-F005(3:1)
               MOVE WS-REC-35 TO WS-REC-34
               MOVE 'Q' TO WS-R35-F014
             WHEN 'C3'
               MOVE SPACES TO WS-R35-G01
               MOVE WS-REC-34 TO WS-REC-35
             WHEN OTHER
               MOVE 'Y' TO WS-R35-F015
               MOVE 'Z' TO WS-R34-F016(1:1)
               MOVE WS-REC-34 TO WS-REC-35
           END-EVALUATE.
       P0278.
           MOVE WS-REC-34 TO WS-REC-35
           MOVE 'Z' TO WS-R35-F013(1:1)
           MOVE SPACES TO WS-R35-G01
           MOVE WS-TAB-04-KEY(WS-IX-2) TO WS-R34-F010
           IF WS-FLAG = 'Y'
               GO TO P0280
           END-IF.
       P0279.
           MOVE 'N' TO WS-R35-F017
           MOVE SPACES TO WS-R34-G04
           MOVE ZERO TO WS-R35-F012
           IF WS-R35-F021 = SPACES
               MOVE 'Q' TO WS-R34-F035
               MOVE 'Q' TO WS-R34-F028
           ELSE
               MOVE SPACES TO WS-R34-G04
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE WS-R34-F024 TO WS-TAB-03-TXT(WS-IX-7)
               MOVE 'F' TO WS-R34-F031
           END-IF.
       P0280.
           MOVE WS-REC-35 TO WS-REC-34
           MOVE 'Z' TO WS-R35-F005(4:1)
           MOVE 'Z' TO WS-R35-F034(2:1)
           MOVE WS-R35-F009 TO WS-TAB-05-KEY(WS-IX-4)
           IF WS-R34-F007 = ZERO
               MOVE ZERO TO WS-R34-F025
               MOVE 'Z' TO WS-R35-F007(3:1)
           ELSE
               MOVE 'Y' TO WS-R34-F029
               MOVE 'V' TO WS-R34-F029
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE WS-REC-34 TO WS-REC-35
           END-IF
           CONTINUE.
       P0281.
           MOVE 'Z' TO WS-R00-F029(15:1)
           MOVE ZERO TO WS-R35-F025
           MOVE WS-REC-35 TO WS-REC-00
           MOVE SPACES TO WS-R00-G00
           IF WS-R35-F030 = SPACES
               MOVE SPACES TO WS-R00-G01
               MOVE WS-R35-F020 TO WS-RDF-00-MID
           ELSE
               MOVE 'R' TO WS-R35-F017
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE 'I' TO WS-R35-F029
               MOVE WS-TAB-00-TXT(WS-IX-5) TO WS-R00-F035
           END-IF.
       P0282.
           MOVE WS-R00-F023 TO WS-TAB-05-KEY(WS-IX-4)
           MOVE 'G' TO WS-R00-F019
           MOVE WS-REC-35 TO WS-REC-00
           MOVE WS-R35-F005 TO WS-RDF-33-MID
           IF WS-FLAG = 'Y'
               GO TO P0288
           END-IF.
       P0283.
           MOVE 'Z' TO WS-R35-F016(5:1)
           MOVE WS-R35-F007 TO WS-TAB-08-KEY(WS-IX-7)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'K' TO WS-R35-F009
               MOVE WS-R35-F002 TO WS-TAB-02-KEY(WS-IX-4)
             WHEN 'B2'
               MOVE WS-REC-35 TO WS-REC-00
               COMPUTE WS-IX-1 = WS-IX-1 + 1
               MOVE ZERO TO WS-R00-F027
             WHEN 'C3'
               MOVE WS-REC-00 TO WS-REC-35
               MOVE 'Z' TO WS-R00-F006(2:1)
               MOVE 'V' TO WS-R00-F002
             WHEN OTHER
               MOVE SPACES TO WS-R35-G00
               MOVE 'Z' TO WS-R35-F009(5:1)
           END-EVALUATE.
       P0284.
           MOVE WS-TAB-02-KEY(WS-IX-5) TO WS-R35-F030
           MOVE 'Z' TO WS-R00-F001(5:1)
           MOVE 'I' TO WS-R00-F003
           MOVE WS-R35-F024 TO WS-TAB-10-KEY(WS-IX-4)
           IF WS-R35-F008 = SPACES
               MOVE 'Z' TO WS-R00-F027(1:1)
               MOVE 'B' TO WS-R35-F009
           ELSE
               MOVE WS-REC-35 TO WS-REC-00
               MOVE WS-R00-F031 TO WS-TAB-01-KEY(WS-IX-3)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0281
           END-IF.
       P0285.
           MOVE 'F' TO WS-R35-F004
           MOVE 'K' TO WS-R00-F031
           MOVE 'K' TO WS-R00-F026
           MOVE 'W' TO WS-R35-F014
           IF WS-R00-F017 = SPACES
               MOVE 'Z' TO WS-R00-F008(1:1)
               COMPUTE WS-IX-4 = WS-IX-4 + 1
           ELSE
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE 'Q' TO WS-R00-F034
               MOVE 'L' TO WS-R00-F028
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0288
           END-IF.
       P0286.
           MOVE 'Q' TO WS-R00-F014
           MOVE 'Q' TO WS-R00-F022
           IF WS-R35-F022 = SPACES
               MOVE ZERO TO WS-R00-F015
               MOVE SPACES TO WS-R35-G03
           ELSE
               MOVE 'Z' TO WS-R00-F018(7:1)
               MOVE 'J' TO WS-R35-F007
               MOVE WS-R00-F008 TO WS-RDF-33-TAIL
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0288
           END-IF.
       P0287.
           MOVE WS-REC-35 TO WS-REC-00
           MOVE 'Q' TO WS-R35-F022
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-R00-F021 TO WS-TAB-09-KEY(WS-IX-2)
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE ZERO TO WS-R00-F015
             WHEN 'B2'
               MOVE WS-R35-F002 TO WS-TAB-04-TXT(WS-IX-3)
               MOVE 'D' TO WS-R00-F006
               MOVE WS-REC-35 TO WS-REC-00
             WHEN 'C3'
               MOVE SPACES TO WS-R35-G05
               MOVE 'K' TO WS-R35-F017
             WHEN OTHER
               MOVE 'W' TO WS-R35-F033
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE SPACES TO WS-R00-G03
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0288
           END-IF.
       P0288.
           MOVE 'Q' TO WS-R00-F035
           MOVE WS-REC-35 TO WS-REC-00
           IF WS-R00-F019 = SPACES
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE 'D' TO WS-R35-F000
               MOVE 'Z' TO WS-R35-F000(2:1)
           ELSE
               MOVE 'A' TO WS-R00-F002
               MOVE 'N' TO WS-R00-F013
           END-IF
           CONTINUE.
       P0289.
           COMPUTE WS-IX-2 = WS-IX-2 + 1
           MOVE WS-REC-01 TO WS-REC-00
           IF WS-R00-F032 = SPACES
               MOVE 'Q' TO WS-R01-F030
               MOVE WS-REC-01 TO WS-REC-00
               MOVE WS-TAB-00-TXT(WS-IX-5) TO WS-R01-F002
               MOVE WS-TAB-01-TXT(WS-IX-6) TO WS-R00-F031
           ELSE
               MOVE SPACES TO WS-R00-G01
               MOVE 'N' TO WS-R01-F016
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0296
           END-IF.
       P0290.
           MOVE WS-R00-F006 TO WS-TAB-05-TXT(WS-IX-1)
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R01-F010
               MOVE WS-TAB-05-TXT(WS-IX-4) TO WS-R00-F016
             WHEN 'B2'
               MOVE 'T' TO WS-R00-F016
               MOVE 'Q' TO WS-R00-F007
               COMPUTE WS-IX-1 = WS-IX-1 + 1
             WHEN 'C3'
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE ZERO TO WS-R00-F009
               MOVE WS-TAB-01-KEY(WS-IX-2) TO WS-R00-F018
             WHEN OTHER
               MOVE 'A' TO WS-R01-F021
               MOVE WS-TAB-08-KEY(WS-IX-5) TO WS-R01-F033
               MOVE 'Z' TO WS-R01-F013(2:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0296
           END-IF.
       P0291.
           MOVE 'G' TO WS-R01-F032
           MOVE SPACES TO WS-R00-G05
           IF WS-FLAG = 'Y'
               GO TO P0289
           END-IF.
       P0292.
           MOVE 'Z' TO WS-R00-F030(4:1)
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'N' TO WS-R00-F034
               MOVE 'L' TO WS-R00-F021
             WHEN 'B2'
               MOVE 'A' TO WS-R01-F024
               MOVE SPACES TO WS-R01-G00
             WHEN 'C3'
               MOVE 'Z' TO WS-R01-F003(7:1)
               MOVE 'Z' TO WS-R01-F005(9:1)
               MOVE WS-REC-00 TO WS-REC-01
             WHEN OTHER
               MOVE 'M' TO WS-R01-F006
               MOVE WS-REC-00 TO WS-REC-01
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0296
           END-IF.
       P0293.
           MOVE 'Q' TO WS-R00-F034
           MOVE ZERO TO WS-R00-F027
           MOVE ZERO TO WS-R00-F020
           IF WS-R01-F010 = ZERO
               MOVE 'F' TO WS-R00-F025
               MOVE 'H' TO WS-R01-F024
               MOVE WS-R00-F022 TO WS-TAB-07-KEY(WS-IX-3)
           ELSE
               MOVE WS-REC-01 TO WS-REC-00
               MOVE ZERO TO WS-R01-F017
           END-IF.
       P0294.
           MOVE 'Z' TO WS-R00-F028(2:1)
           MOVE 'R' TO WS-R00-F026
           MOVE WS-REC-00 TO WS-REC-01
           MOVE 'T' TO WS-R00-F022
           IF WS-R00-F034 = SPACES
               MOVE WS-R01-F020 TO WS-RDF-00-MID
               MOVE WS-TAB-07-KEY(WS-IX-5) TO WS-R00-F029
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE WS-TAB-03-TXT(WS-IX-3) TO WS-R01-F009
           ELSE
               MOVE 'Z' TO WS-R01-F012(8:1)
               MOVE ZERO TO WS-R01-F030
               MOVE 'Z' TO WS-R01-F012(5:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0296
           END-IF.
       P0295.
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE 'I' TO WS-R01-F012
           MOVE SPACES TO WS-R01-G05
           MOVE 'Y' TO WS-R00-F013
           IF WS-FLAG = 'Y'
               GO TO P0296
           END-IF.
       P0296.
           MOVE WS-REC-01 TO WS-REC-00
           MOVE 'L' TO WS-R00-F034
           IF WS-R01-F002 = ZERO
               MOVE 'R' TO WS-R01-F035
               MOVE WS-R00-F001 TO WS-RDF-00-MID
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE WS-R00-F018 TO WS-TAB-04-KEY(WS-IX-1)
           ELSE
               MOVE WS-R00-F018 TO WS-RDF-00-TAIL
               MOVE WS-R00-F004 TO WS-RDF-00-MID
               MOVE 'Q' TO WS-R00-F022
               MOVE 'Z' TO WS-R01-F012(6:1)
           END-IF
           CONTINUE.
       P0297.
           MOVE WS-REC-02 TO WS-REC-01
           MOVE 'U' TO WS-R02-F001
           MOVE 'X' TO WS-R01-F004
           IF WS-R01-F003 = SPACES
               MOVE 'Z' TO WS-R01-F035(2:1)
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               COMPUTE WS-IX-7 = WS-IX-7 + 1
           ELSE
               MOVE 'R' TO WS-R02-F033
               MOVE 'Q' TO WS-R01-F022
               MOVE WS-TAB-04-KEY(WS-IX-3) TO WS-R01-F015
               MOVE WS-REC-02 TO WS-REC-01
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0304
           END-IF.
       P0298.
           MOVE WS-R01-F008 TO WS-RDF-00-HEAD
           MOVE 'Y' TO WS-R01-F008
           IF WS-R02-F006 = SPACES
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE WS-REC-02 TO WS-REC-01
               MOVE WS-REC-02 TO WS-REC-01
           ELSE
               MOVE WS-R01-F024 TO WS-RDF-00-MID
               MOVE WS-TAB-02-KEY(WS-IX-2) TO WS-R01-F008
               MOVE WS-REC-01 TO WS-REC-02
               MOVE 'Z' TO WS-R01-F025(6:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0304
           END-IF.
       P0299.
           MOVE WS-TAB-01-KEY(WS-IX-2) TO WS-R02-F024
           MOVE 'F' TO WS-R01-F011
           IF WS-R02-F026 = SPACES
               MOVE WS-R02-F009 TO WS-TAB-00-KEY(WS-IX-4)
               MOVE SPACES TO WS-R02-G03
               MOVE WS-R02-F006 TO WS-RDF-00-TAIL
           ELSE
               MOVE WS-TAB-01-KEY(WS-IX-5) TO WS-R01-F025
               MOVE WS-R01-F013 TO WS-TAB-02-KEY(WS-IX-3)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0304
           END-IF.
       P0300.
           MOVE 'J' TO WS-R01-F025
           MOVE SPACES TO WS-R02-G02
           MOVE 'Z' TO WS-R02-F006(4:1)
           MOVE SPACES TO WS-R01-G04
           IF WS-R01-F012 = SPACES
               MOVE WS-REC-01 TO WS-REC-02
               MOVE ZERO TO WS-R02-F025
           ELSE
               MOVE SPACES TO WS-R02-G01
               MOVE ZERO TO WS-R02-F013
               MOVE WS-TAB-03-TXT(WS-IX-0) TO WS-R02-F013
               MOVE ZERO TO WS-R01-F010
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0304
           END-IF.
       P0301.
           MOVE 'Z' TO WS-R02-F035(2:1)
           MOVE ZERO TO WS-R01-F023
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-02 TO WS-REC-01
               MOVE WS-R01-F017 TO WS-TAB-05-TXT(WS-IX-3)
               MOVE WS-REC-02 TO WS-REC-01
             WHEN 'B2'
               MOVE SPACES TO WS-R01-G03
               MOVE WS-TAB-10-KEY(WS-IX-4) TO WS-R01-F005
             WHEN 'C3'
               MOVE 'E' TO WS-R01-F013
               MOVE WS-REC-01 TO WS-REC-02
             WHEN OTHER
               MOVE WS-REC-02 TO WS-REC-01
               MOVE 'Z' TO WS-R02-F015(4:1)
               MOVE 'Z' TO WS-R01-F028(5:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0304
           END-IF.
       P0302.
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE WS-REC-01 TO WS-REC-02
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE SPACES TO WS-R02-G02
               MOVE WS-REC-01 TO WS-REC-02
               MOVE 'Z' TO WS-R02-F003(9:1)
             WHEN 'B2'
               MOVE 'Z' TO WS-R01-F005(4:1)
               MOVE 'Z' TO WS-R02-F022
             WHEN 'C3'
               MOVE 'T' TO WS-R02-F010
               MOVE 'Z' TO WS-R02-F004
               COMPUTE WS-IX-5 = WS-IX-5 + 1
             WHEN OTHER
               MOVE 'Z' TO WS-R02-F013(2:1)
               MOVE ZERO TO WS-R01-F002
               MOVE ZERO TO WS-R02-F009
           END-EVALUATE.
       P0303.
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           MOVE 'Q' TO WS-R01-F000
           MOVE ZERO TO WS-R01-F019
           MOVE 'B' TO WS-R02-F004
           IF WS-R01-F011 = SPACES
               MOVE 'Z' TO WS-R02-F006(3:1)
               MOVE WS-REC-02 TO WS-REC-01
               MOVE SPACES TO WS-R01-G02
           ELSE
               MOVE WS-R01-F030 TO WS-RDF-00-MID
               MOVE WS-R02-F024 TO WS-RDF-00-HEAD
               MOVE WS-REC-02 TO WS-REC-01
           END-IF.
       P0304.
           MOVE WS-REC-02 TO WS-REC-01
           MOVE 'F' TO WS-R01-F028
           IF WS-R01-F022 = SPACES
               MOVE WS-TAB-06-TXT(WS-IX-4) TO WS-R01-F008
               MOVE WS-REC-02 TO WS-REC-01
               MOVE 'G' TO WS-R01-F020
               MOVE 'I' TO WS-R02-F029
           ELSE
               MOVE SPACES TO WS-R01-G03
               MOVE WS-R01-F001 TO WS-TAB-09-TXT(WS-IX-2)
           END-IF
           CONTINUE.
       P0305.
           MOVE SPACES TO WS-R02-G01
           MOVE 'Q' TO WS-R02-F004
           IF WS-R03-F008 = SPACES
               MOVE 'Z' TO WS-R03-F008(1:1)
               MOVE 'Q' TO WS-R03-F031
           ELSE
               MOVE 'Z' TO WS-R03-F018(4:1)
               MOVE WS-REC-03 TO WS-REC-02
               MOVE WS-REC-03 TO WS-REC-02
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0312
           END-IF.
       P0306.
           MOVE WS-R03-F023 TO WS-TAB-03-TXT(WS-IX-4)
           MOVE WS-REC-03 TO WS-REC-02
           IF WS-R03-F013 = SPACES
               MOVE SPACES TO WS-R03-G03
               MOVE SPACES TO WS-R02-G04
               MOVE 'Z' TO WS-R02-F016(14:1)
               COMPUTE WS-IX-4 = WS-IX-4 + 1
           ELSE
               MOVE WS-REC-03 TO WS-REC-02
               MOVE 'Z' TO WS-R02-F028(4:1)
               MOVE 'Z' TO WS-R03-F003(4:1)
           END-IF.
       P0307.
           MOVE 'O' TO WS-R02-F028
           COMPUTE WS-IX-5 = WS-IX-5 + 1
           MOVE 'K' TO WS-R03-F011.
       P0308.
           MOVE WS-REC-02 TO WS-REC-03
           MOVE WS-REC-03 TO WS-REC-02
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-03 TO WS-REC-02
               MOVE WS-R02-F005 TO WS-TAB-00-KEY(WS-IX-3)
               MOVE WS-REC-02 TO WS-REC-03
             WHEN 'B2'
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE 'M' TO WS-R03-F029
             WHEN 'C3'
               MOVE 'F' TO WS-R03-F023
               MOVE 'Q' TO WS-R03-F033
               MOVE 'Q' TO WS-R03-F020
             WHEN OTHER
               MOVE WS-REC-03 TO WS-REC-02
               MOVE 'Z' TO WS-R02-F019(3:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0305
           END-IF.
       P0309.
           MOVE WS-R03-F009 TO WS-RDF-00-MID
           MOVE WS-REC-02 TO WS-REC-03
           IF WS-R02-F001 = SPACES
               MOVE 'Q' TO WS-R03-F024
               MOVE WS-TAB-05-KEY(WS-IX-0) TO WS-R02-F020
           ELSE
               MOVE WS-REC-03 TO WS-REC-02
               MOVE 'R' TO WS-R02-F029
               MOVE WS-TAB-09-KEY(WS-IX-7) TO WS-R03-F009
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0312
           END-IF.
       P0310.
           MOVE WS-REC-02 TO WS-REC-03
           MOVE WS-TAB-03-KEY(WS-IX-2) TO WS-R03-F012
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE WS-REC-03 TO WS-REC-02
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE ZERO TO WS-R02-F003
             WHEN 'B2'
               MOVE WS-REC-03 TO WS-REC-02
               MOVE WS-REC-03 TO WS-REC-02
               COMPUTE WS-IX-1 = WS-IX-1 + 1
             WHEN 'C3'
               MOVE ZERO TO WS-R03-F032
               MOVE SPACES TO WS-R03-G00
             WHEN OTHER
               MOVE 'O' TO WS-R02-F024
               MOVE ZERO TO WS-R02-F009
               MOVE 'Z' TO WS-R03-F017(6:1)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0305
           END-IF.
       P0311.
           MOVE 'I' TO WS-R03-F012
           MOVE ZERO TO WS-R02-F027
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE SPACES TO WS-R03-G04
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R02-F001(6:1)
               MOVE 'Q' TO WS-R02-F014
               MOVE 'Z' TO WS-R02-F028(6:1)
             WHEN 'B2'
               MOVE WS-REC-03 TO WS-REC-02
               MOVE WS-REC-02 TO WS-REC-03
               MOVE WS-REC-02 TO WS-REC-03
             WHEN 'C3'
               MOVE 'L' TO WS-R03-F026
               MOVE WS-TAB-05-TXT(WS-IX-4) TO WS-R02-F017
               MOVE WS-TAB-05-KEY(WS-IX-3) TO WS-R02-F013
             WHEN OTHER
               MOVE 'F' TO WS-R03-F034
               MOVE WS-R03-F023 TO WS-RDF-03-MID
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0312
           END-IF.
       P0312.
           MOVE WS-REC-02 TO WS-REC-03
           MOVE SPACES TO WS-R02-G02
           IF WS-R03-F004 = SPACES
               MOVE 'Z' TO WS-R02-F003(5:1)
               MOVE WS-REC-02 TO WS-REC-03
           ELSE
               MOVE WS-TAB-02-TXT(WS-IX-5) TO WS-R02-F026
               MOVE SPACES TO WS-R02-G02
               MOVE 'Q' TO WS-R02-F020
               MOVE SPACES TO WS-R02-G04
           END-IF
           CONTINUE.
       P0313.
           MOVE 'Z' TO WS-R04-F034(6:1)
           MOVE 'Z' TO WS-R04-F031(1:1)
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-5 = WS-IX-5 + 1
               MOVE 'Z' TO WS-R03-F023(15:1)
             WHEN 'B2'
               MOVE 'O' TO WS-R04-F018
               MOVE 'Z' TO WS-R04-F004(5:1)
               MOVE ZERO TO WS-R03-F032
             WHEN 'C3'
               MOVE 'B' TO WS-R03-F012
               MOVE WS-R04-F005 TO WS-RDF-03-HEAD
             WHEN OTHER
               MOVE WS-R03-F006 TO WS-RDF-03-MID
               MOVE SPACES TO WS-R03-G01
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0320
           END-IF.
       P0314.
           MOVE WS-TAB-04-KEY(WS-IX-2) TO WS-R04-F006
           MOVE 'C' TO WS-R04-F012
           MOVE SPACES TO WS-R03-G01
           MOVE 'L' TO WS-R03-F019
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE WS-REC-04 TO WS-REC-03
               MOVE 'N' TO WS-R04-F003
             WHEN 'B2'
               MOVE WS-R04-F002 TO WS-TAB-11-KEY(WS-IX-6)
               MOVE WS-REC-04 TO WS-REC-03
               MOVE 'Z' TO WS-R04-F031
             WHEN 'C3'
               MOVE WS-TAB-03-KEY(WS-IX-2) TO WS-R03-F022
               MOVE WS-R04-F034 TO WS-RDF-03-TAIL
               MOVE 'K' TO WS-R03-F004
             WHEN OTHER
               MOVE 'Y' TO WS-R03-F007
               MOVE 'N' TO WS-R04-F007
               MOVE WS-REC-03 TO WS-REC-04
           END-EVALUATE.
       P0315.
           MOVE 'Z' TO WS-R03-F026(4:1)
           MOVE 'S' TO WS-R03-F022
           MOVE 'R' TO WS-R03-F008
           MOVE 'Z' TO WS-R04-F005(9:1)
           IF WS-FLAG = 'Y'
               GO TO P0320
           END-IF.
       P0316.
           MOVE 'Z' TO WS-R04-F012(2:1)
           MOVE SPACES TO WS-R04-G00
           MOVE 'C' TO WS-R04-F016
           MOVE WS-R04-F031 TO WS-TAB-06-TXT(WS-IX-3)
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R04-F028
               MOVE WS-R03-F005 TO WS-RDF-03-HEAD
             WHEN 'B2'
               MOVE WS-REC-03 TO WS-REC-04
               MOVE 'X' TO WS-R03-F013
               MOVE 'Q' TO WS-R04-F001
             WHEN 'C3'
               MOVE WS-R04-F023 TO WS-TAB-02-KEY(WS-IX-6)
               MOVE 'Z' TO WS-R04-F032
             WHEN OTHER
               MOVE WS-R03-F034 TO WS-TAB-03-TXT(WS-IX-7)
               MOVE WS-R03-F027 TO WS-RDF-03-TAIL
               MOVE 'R' TO WS-R04-F026
           END-EVALUATE.
       P0317.
           MOVE WS-REC-03 TO WS-REC-04
           MOVE WS-R04-F033 TO WS-TAB-11-KEY(WS-IX-1)
           MOVE 'Y' TO WS-R04-F007
           MOVE 'Q' TO WS-R04-F009
           IF WS-R04-F012 = SPACES
               MOVE WS-REC-04 TO WS-REC-03
               MOVE WS-REC-04 TO WS-REC-03
           ELSE
               MOVE 'F' TO WS-R04-F031
               MOVE SPACES TO WS-R04-G00
               MOVE WS-R04-F029 TO WS-TAB-11-KEY(WS-IX-6)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0320
           END-IF.
       P0318.
           MOVE WS-REC-04 TO WS-REC-03
           MOVE 'Z' TO WS-R04-F011(1:1)
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R03-F004(18:1)
               MOVE 'O' TO WS-R03-F025
               MOVE WS-R03-F034 TO WS-TAB-04-TXT(WS-IX-7)
             WHEN 'B2'
               MOVE ZERO TO WS-R04-F028
               MOVE 'U' TO WS-R03-F002
               MOVE WS-R03-F009 TO WS-TAB-11-TXT(WS-IX-1)
             WHEN 'C3'
               MOVE SPACES TO WS-R04-G03
               MOVE WS-R03-F025 TO WS-RDF-03-MID
               MOVE WS-REC-04 TO WS-REC-03
             WHEN OTHER
               MOVE WS-REC-04 TO WS-REC-03
               MOVE WS-REC-04 TO WS-REC-03
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0313
           END-IF.
       P0319.
           MOVE 'S' TO WS-R04-F014
           MOVE 'W' TO WS-R03-F035
           MOVE SPACES TO WS-R04-G04
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-04 TO WS-REC-03
               MOVE 'Q' TO WS-R04-F022
               MOVE WS-TAB-05-TXT(WS-IX-7) TO WS-R04-F012
             WHEN 'B2'
               MOVE WS-REC-03 TO WS-REC-04
               MOVE WS-R04-F025 TO WS-RDF-03-MID
             WHEN 'C3'
               MOVE WS-REC-03 TO WS-REC-04
               MOVE SPACES TO WS-R03-G02
               MOVE SPACES TO WS-R03-G01
             WHEN OTHER
               MOVE 'Q' TO WS-R03-F005
               MOVE 'Q' TO WS-R04-F001
               MOVE WS-R04-F004 TO WS-RDF-03-TAIL
           END-EVALUATE.
       P0320.
           MOVE SPACES TO WS-R04-G02
           MOVE 'Q' TO WS-R04-F010
           MOVE SPACES TO WS-R04-G00
           IF WS-R03-F028 = SPACES
               MOVE SPACES TO WS-R03-G01
               MOVE 'Z' TO WS-R03-F014(1:1)
               MOVE SPACES TO WS-R03-G05
               MOVE WS-TAB-02-KEY(WS-IX-0) TO WS-R03-F002
           ELSE
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE WS-REC-03 TO WS-REC-04
               MOVE WS-REC-03 TO WS-REC-04
               MOVE WS-TAB-01-KEY(WS-IX-0) TO WS-R04-F010
           END-IF
           CONTINUE.
       P0321.
           MOVE SPACES TO WS-R04-G05
           MOVE WS-R04-F018 TO WS-RDF-03-MID
           IF WS-FLAG = 'Y'
               GO TO P0328
           END-IF.
       P0322.
           MOVE WS-R05-F015 TO WS-TAB-06-KEY(WS-IX-6)
           MOVE WS-TAB-05-TXT(WS-IX-3) TO WS-R04-F002
           MOVE WS-REC-04 TO WS-REC-05
           MOVE WS-REC-04 TO WS-REC-05
           IF WS-R04-F007 = SPACES
               MOVE WS-REC-05 TO WS-REC-04
               MOVE WS-REC-04 TO WS-REC-05
               MOVE WS-REC-05 TO WS-REC-04
               COMPUTE WS-IX-4 = WS-IX-4 + 1
           ELSE
               MOVE 'N' TO WS-R04-F013
               MOVE WS-REC-05 TO WS-REC-04
               MOVE WS-R04-F003 TO WS-RDF-03-HEAD
               MOVE 'S' TO WS-R05-F027
           END-IF.
       P0323.
           MOVE 'G' TO WS-R04-F007
           MOVE WS-REC-04 TO WS-REC-05
           MOVE 'Z' TO WS-R05-F013(8:1)
           IF WS-FLAG = 'Y'
               GO TO P0328
           END-IF.
       P0324.
           MOVE WS-R04-F013 TO WS-RDF-03-TAIL
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           IF WS-FLAG = 'Y'
               GO TO P0328
           END-IF.
       P0325.
           MOVE 'J' TO WS-R04-F007
           MOVE SPACES TO WS-R05-G02
           MOVE 'Q' TO WS-R05-F017
           MOVE WS-REC-04 TO WS-REC-05
           IF WS-R05-F016 = SPACES
               MOVE ZERO TO WS-R05-F023
               MOVE 'Z' TO WS-R04-F031(4:1)
               MOVE 'Q' TO WS-R04-F033
           ELSE
               MOVE 'J' TO WS-R04-F021
               MOVE WS-TAB-05-TXT(WS-IX-6) TO WS-R05-F026
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0328
           END-IF.
       P0326.
           MOVE ZERO TO WS-R05-F026
           MOVE 'G' TO WS-R05-F013
           IF WS-R05-F003 = SPACES
               MOVE WS-TAB-08-KEY(WS-IX-5) TO WS-R04-F006
               MOVE WS-REC-04 TO WS-REC-05
               MOVE ZERO TO WS-R05-F032
               MOVE SPACES TO WS-R04-G05
           ELSE
               MOVE WS-R04-F030 TO WS-RDF-03-TAIL
               MOVE WS-REC-05 TO WS-REC-04
               MOVE 'Z' TO WS-R05-F024(1:1)
               MOVE SPACES TO WS-R05-G04
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0321
           END-IF.
       P0327.
           MOVE WS-TAB-03-KEY(WS-IX-4) TO WS-R05-F034
           MOVE 'V' TO WS-R04-F030
           MOVE WS-R04-F032 TO WS-RDF-03-TAIL
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R04-F000(10:1)
               MOVE WS-REC-05 TO WS-REC-04
               MOVE WS-R05-F033 TO WS-RDF-03-TAIL
             WHEN 'B2'
               MOVE SPACES TO WS-R05-G02
               MOVE WS-R04-F013 TO WS-TAB-02-KEY(WS-IX-7)
               MOVE SPACES TO WS-R04-G01
             WHEN 'C3'
               MOVE 'D' TO WS-R04-F018
               MOVE WS-R05-F033 TO WS-TAB-02-KEY(WS-IX-0)
             WHEN OTHER
               MOVE 'Q' TO WS-R05-F027
               MOVE WS-R04-F012 TO WS-TAB-00-KEY(WS-IX-3)
               MOVE WS-REC-04 TO WS-REC-05
           END-EVALUATE.
       P0328.
           MOVE SPACES TO WS-R05-G00
           MOVE WS-TAB-10-TXT(WS-IX-2) TO WS-R05-F004
           MOVE 'I' TO WS-R04-F006
           MOVE 'Z' TO WS-R04-F025(1:1)
           CONTINUE.
       P0329.
           MOVE 'Z' TO WS-R06-F035(1:1)
           MOVE 'O' TO WS-R05-F017
           MOVE WS-R05-F003 TO WS-RDF-06-TAIL.
       P0330.
           MOVE 'Q' TO WS-R05-F006
           MOVE 'Z' TO WS-R05-F018(1:1)
           MOVE ZERO TO WS-R05-F024
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R06-F004
               MOVE 'Z' TO WS-R06-F015(2:1)
               COMPUTE WS-IX-1 = WS-IX-1 + 1
             WHEN 'B2'
               MOVE WS-R05-F007 TO WS-RDF-03-MID
               MOVE WS-REC-06 TO WS-REC-05
               MOVE WS-R06-F020 TO WS-RDF-06-TAIL
             WHEN 'C3'
               MOVE WS-REC-06 TO WS-REC-05
               MOVE WS-REC-06 TO WS-REC-05
               COMPUTE WS-IX-6 = WS-IX-6 + 1
             WHEN OTHER
               MOVE 'Z' TO WS-R05-F027(1:1)
               MOVE WS-R05-F028 TO WS-RDF-03-TAIL
               MOVE WS-R05-F029 TO WS-TAB-09-KEY(WS-IX-3)
           END-EVALUATE.
       P0331.
           MOVE WS-TAB-10-KEY(WS-IX-4) TO WS-R05-F000
           MOVE ZERO TO WS-R05-F024
           MOVE WS-R05-F007 TO WS-RDF-03-MID
           IF WS-R06-F015 = SPACES
               MOVE WS-REC-06 TO WS-REC-05
               MOVE SPACES TO WS-R05-G02
           ELSE
               MOVE ZERO TO WS-R06-F029
               MOVE WS-REC-05 TO WS-REC-06
               MOVE WS-REC-05 TO WS-REC-06
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0336
           END-IF.
       P0332.
           MOVE WS-REC-06 TO WS-REC-05
           MOVE ZERO TO WS-R05-F023
           MOVE WS-R05-F007 TO WS-TAB-07-TXT(WS-IX-4)
           MOVE 'T' TO WS-R05-F015
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R05-F020
               MOVE WS-REC-06 TO WS-REC-05
             WHEN 'B2'
               MOVE WS-R05-F003 TO WS-RDF-03-TAIL
               MOVE WS-REC-06 TO WS-REC-05
               MOVE WS-REC-06 TO WS-REC-05
             WHEN 'C3'
               MOVE WS-TAB-11-KEY(WS-IX-6) TO WS-R05-F021
               MOVE WS-REC-06 TO WS-REC-05
               MOVE 'Z' TO WS-R05-F027(1:1)
             WHEN OTHER
               MOVE 'Z' TO WS-R05-F022(3:1)
               MOVE 'L' TO WS-R06-F005
               MOVE WS-R06-F030 TO WS-TAB-01-TXT(WS-IX-4)
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0336
           END-IF.
       P0333.
           MOVE 'W' TO WS-R06-F030
           MOVE SPACES TO WS-R06-G03
           MOVE 'Q' TO WS-R05-F020
           MOVE 'Z' TO WS-R06-F024(1:1)
           IF WS-R05-F016 = SPACES
               MOVE 'Z' TO WS-R06-F004(2:1)
               MOVE 'Q' TO WS-R05-F011
               MOVE ZERO TO WS-R05-F000
           ELSE
               MOVE WS-REC-05 TO WS-REC-06
               MOVE WS-R05-F013 TO WS-RDF-06-TAIL
           END-IF.
       P0334.
           MOVE WS-R06-F018 TO WS-TAB-07-TXT(WS-IX-0)
           MOVE ZERO TO WS-R05-F026
           MOVE 'Z' TO WS-R05-F019(5:1)
           IF WS-R06-F005 = SPACES
               MOVE SPACES TO WS-R06-G02
               MOVE WS-REC-05 TO WS-REC-06
               MOVE 'H' TO WS-R06-F001
           ELSE
               MOVE 'Z' TO WS-R06-F020(2:1)
               MOVE 'Z' TO WS-R05-F033(8:1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0336
           END-IF.
       P0335.
           MOVE WS-REC-06 TO WS-REC-05
           MOVE 'P' TO WS-R05-F030
           MOVE WS-R05-F003 TO WS-TAB-05-KEY(WS-IX-7)
           MOVE 'T' TO WS-R05-F025
           IF WS-R06-F004 = ZERO
               MOVE ZERO TO WS-R05-F024
               MOVE WS-R05-F033 TO WS-RDF-06-TAIL
               MOVE 'O' TO WS-R06-F031
           ELSE
               MOVE 'P' TO WS-R05-F007
               MOVE SPACES TO WS-R06-G02
               MOVE WS-TAB-02-KEY(WS-IX-3) TO WS-R05-F020
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0336
           END-IF.
       P0336.
           MOVE WS-R05-F023 TO WS-RDF-06-HEAD
           MOVE WS-R06-F012 TO WS-RDF-03-MID
           MOVE SPACES TO WS-R06-G01
           MOVE 'Z' TO WS-R06-F005
           CONTINUE.
       P0337.
           MOVE 'E' TO WS-R07-F020
           COMPUTE WS-IX-0 = WS-IX-0 + 1
           MOVE 'Z' TO WS-R07-F010(2:1)
           MOVE SPACES TO WS-R07-G04.
       P0338.
           MOVE 'F' TO WS-R06-F012
           MOVE 'Q' TO WS-R07-F027
           IF WS-R06-F016 = SPACES
               COMPUTE WS-IX-0 = WS-IX-0 + 1
               MOVE 'I' TO WS-R07-F026
           ELSE
               MOVE 'M' TO WS-R06-F034
               MOVE 'B' TO WS-R06-F016
           END-IF.
       P0339.
           MOVE 'Z' TO WS-R06-F000(1:1)
           MOVE 'C' TO WS-R07-F024
           MOVE WS-REC-07 TO WS-REC-06
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'J' TO WS-R06-F034
               MOVE 'G' TO WS-R06-F032
               MOVE 'Q' TO WS-R07-F027
             WHEN 'B2'
               MOVE 'J' TO WS-R06-F016
               MOVE ZERO TO WS-R06-F019
             WHEN 'C3'
               MOVE WS-REC-06 TO WS-REC-07
               MOVE ZERO TO WS-R07-F011
               MOVE WS-TAB-05-TXT(WS-IX-3) TO WS-R06-F027
             WHEN OTHER
               MOVE WS-R06-F031 TO WS-TAB-09-KEY(WS-IX-0)
               MOVE 'K' TO WS-R07-F030
               MOVE WS-TAB-02-TXT(WS-IX-5) TO WS-R07-F019
           END-EVALUATE.
       P0340.
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE WS-REC-06 TO WS-REC-07
           EVALUATE WS-MODE
             WHEN 'A1'
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE 'Z' TO WS-R06-F002(2:1)
             WHEN 'B2'
               MOVE 'V' TO WS-R07-F008
               MOVE WS-R06-F016 TO WS-RDF-06-TAIL
               MOVE WS-TAB-05-KEY(WS-IX-5) TO WS-R07-F004
             WHEN 'C3'
               MOVE 'E' TO WS-R06-F005
               MOVE 'N' TO WS-R07-F032
               MOVE WS-REC-06 TO WS-REC-07
             WHEN OTHER
               MOVE SPACES TO WS-R07-G01
               MOVE 'Q' TO WS-R06-F005
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0337
           END-IF.
       P0341.
           MOVE WS-TAB-02-KEY(WS-IX-1) TO WS-R07-F008
           MOVE WS-TAB-05-KEY(WS-IX-7) TO WS-R06-F006
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE 'E' TO WS-R07-F008
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-07 TO WS-REC-06
               MOVE SPACES TO WS-R07-G03
             WHEN 'B2'
               MOVE WS-R07-F034 TO WS-TAB-08-TXT(WS-IX-2)
               COMPUTE WS-IX-4 = WS-IX-4 + 1
               MOVE WS-R06-F019 TO WS-RDF-06-MID
             WHEN 'C3'
               MOVE 'Z' TO WS-R06-F032(15:1)
               MOVE WS-R06-F008 TO WS-RDF-06-TAIL
               MOVE WS-REC-07 TO WS-REC-06
             WHEN OTHER
               MOVE WS-REC-06 TO WS-REC-07
               MOVE 'R' TO WS-R06-F008
               MOVE WS-TAB-09-KEY(WS-IX-7) TO WS-R07-F012
           END-EVALUATE.
       P0342.
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE 'S' TO WS-R06-F031
           IF WS-R06-F033 = SPACES
               MOVE 'Q' TO WS-R07-F015
               MOVE WS-REC-06 TO WS-REC-07
               MOVE 'B' TO WS-R06-F005
           ELSE
               MOVE 'Z' TO WS-R07-F011(2:1)
               MOVE WS-REC-07 TO WS-REC-06
           END-IF.
       P0343.
           MOVE 'Q' TO WS-R06-F007
           MOVE ZERO TO WS-R07-F019
           MOVE 'Z' TO WS-R06-F029(4:1)
           MOVE 'C' TO WS-R06-F012
           IF WS-FLAG = 'Y'
               GO TO P0344
           END-IF.
       P0344.
           MOVE ZERO TO WS-R07-F006
           MOVE 'R' TO WS-R06-F002
           MOVE ZERO TO WS-R07-F033
           MOVE 'Q' TO WS-R07-F006
           CONTINUE.
       P0345.
           MOVE 'M' TO WS-R07-F007
           MOVE WS-R08-F011 TO WS-TAB-06-TXT(WS-IX-6)
           MOVE WS-R07-F004 TO WS-RDF-06-HEAD
           IF WS-R08-F030 = ZERO
               MOVE WS-REC-07 TO WS-REC-08
               MOVE WS-R08-F010 TO WS-RDF-06-MID
               MOVE WS-REC-08 TO WS-REC-07
               MOVE 'Z' TO WS-R07-F033(5:1)
           ELSE
               MOVE SPACES TO WS-R08-G05
               MOVE 'S' TO WS-R08-F017
               MOVE WS-REC-08 TO WS-REC-07
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0352
           END-IF.
       P0346.
           MOVE SPACES TO WS-R07-G02
           COMPUTE WS-IX-5 = WS-IX-5 + 1
           MOVE 'L' TO WS-R07-F014
           IF WS-R07-F035 = ZERO
               MOVE WS-R08-F019 TO WS-RDF-06-MID
               MOVE 'Z' TO WS-R08-F002(3:1)
           ELSE
               MOVE WS-REC-07 TO WS-REC-08
               MOVE 'Z' TO WS-R08-F025(6:1)
               MOVE WS-R07-F002 TO WS-RDF-06-MID
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0345
           END-IF.
       P0347.
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           MOVE SPACES TO WS-R08-G04
           MOVE WS-REC-07 TO WS-REC-08
           IF WS-R08-F005 = SPACES
               MOVE 'H' TO WS-R07-F020
               MOVE 'Z' TO WS-R07-F017(2:1)
           ELSE
               MOVE WS-REC-08 TO WS-REC-07
               MOVE 'Z' TO WS-R07-F015(6:1)
               MOVE 'Z' TO WS-R08-F009(6:1)
               MOVE WS-R08-F031 TO WS-TAB-04-KEY(WS-IX-1)
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0345
           END-IF.
       P0348.
           MOVE 'H' TO WS-R07-F004
           MOVE ZERO TO WS-R08-F031
           MOVE WS-REC-08 TO WS-REC-07
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           IF WS-FLAG = 'Y'
               GO TO P0352
           END-IF.
       P0349.
           MOVE WS-REC-07 TO WS-REC-08
           MOVE 'Z' TO WS-R07-F015(4:1)
           IF WS-R07-F014 = SPACES
               COMPUTE WS-IX-7 = WS-IX-7 + 1
               MOVE ZERO TO WS-R07-F018
               MOVE 'Z' TO WS-R07-F008
               COMPUTE WS-IX-2 = WS-IX-2 + 1
           ELSE
               MOVE 'Q' TO WS-R08-F012
               MOVE ZERO TO WS-R07-F017
           END-IF
           IF WS-FLAG = 'Y'
               GO TO P0352
           END-IF.
       P0350.
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE 'Z' TO WS-R08-F021(2:1).
       P0351.
           MOVE WS-REC-08 TO WS-REC-07
           COMPUTE WS-IX-4 = WS-IX-4 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Q' TO WS-R08-F011
               MOVE 'M' TO WS-R08-F024
             WHEN 'B2'
               MOVE 'Z' TO WS-R07-F026(2:1)
               MOVE 'O' TO WS-R07-F005
               MOVE SPACES TO WS-R07-G00
             WHEN 'C3'
               COMPUTE WS-IX-2 = WS-IX-2 + 1
               MOVE 'Z' TO WS-R07-F009(1:1)
               MOVE WS-R08-F013 TO WS-TAB-04-KEY(WS-IX-4)
             WHEN OTHER
               MOVE WS-R07-F007 TO WS-TAB-01-TXT(WS-IX-0)
               MOVE WS-R07-F033 TO WS-RDF-06-HEAD
               MOVE 'I' TO WS-R08-F012
           END-EVALUATE.
       P0352.
           MOVE WS-R08-F032 TO WS-RDF-06-TAIL
           MOVE WS-R07-F003 TO WS-TAB-05-TXT(WS-IX-0)
           MOVE 'Z' TO WS-R08-F031(8:1)
           COMPUTE WS-IX-6 = WS-IX-6 + 1
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE WS-REC-07 TO WS-REC-08
               MOVE WS-R07-F018 TO WS-RDF-06-MID
             WHEN 'B2'
               MOVE WS-TAB-08-KEY(WS-IX-6) TO WS-R07-F029
               MOVE 'Q' TO WS-R07-F025
             WHEN 'C3'
               COMPUTE WS-IX-6 = WS-IX-6 + 1
               MOVE 'L' TO WS-R07-F028
               MOVE ZERO TO WS-R08-F014
             WHEN OTHER
               MOVE 'Q' TO WS-R07-F016
               MOVE WS-R07-F025 TO WS-RDF-06-MID
           END-EVALUATE
           CONTINUE.
       P0353.
           MOVE WS-REC-09 TO WS-REC-08
           MOVE 'Z' TO WS-R09-F000(2:1)
           MOVE WS-REC-09 TO WS-REC-08
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'Z' TO WS-R09-F010(2:1)
               MOVE WS-REC-09 TO WS-REC-08
               MOVE WS-REC-09 TO WS-REC-08
             WHEN 'B2'
               MOVE WS-TAB-10-TXT(WS-IX-6) TO WS-R08-F012
               MOVE WS-REC-09 TO WS-REC-08
               MOVE WS-TAB-10-TXT(WS-IX-3) TO WS-R08-F008
             WHEN 'C3'
               MOVE SPACES TO WS-R08-G00
               MOVE WS-REC-09 TO WS-REC-08
             WHEN OTHER
               MOVE WS-R09-F030 TO WS-RDF-06-TAIL
               MOVE WS-REC-08 TO WS-REC-09
               MOVE 'M' TO WS-R09-F002
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0360
           END-IF.
       P0354.
           MOVE SPACES TO WS-R09-G03
           MOVE WS-TAB-00-KEY(WS-IX-3) TO WS-R08-F007
           IF WS-FLAG = 'Y'
               GO TO P0353
           END-IF.
       P0355.
           MOVE SPACES TO WS-R08-G05
           MOVE 'H' TO WS-R08-F001
           COMPUTE WS-IX-7 = WS-IX-7 + 1
           MOVE 'K' TO WS-R09-F035.
       P0356.
           MOVE 'Z' TO WS-R08-F033(2:1)
           MOVE WS-REC-08 TO WS-REC-09
           MOVE 'C' TO WS-R08-F025
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE 'H' TO WS-R09-F028
               COMPUTE WS-IX-3 = WS-IX-3 + 1
               MOVE 'O' TO WS-R08-F017
             WHEN 'B2'
               MOVE ZERO TO WS-R09-F015
               MOVE WS-REC-08 TO WS-REC-09
             WHEN 'C3'
               MOVE WS-R09-F011 TO WS-TAB-01-KEY(WS-IX-7)
               MOVE 'Z' TO WS-R08-F019(6:1)
             WHEN OTHER
               MOVE 'X' TO WS-R08-F007
               MOVE SPACES TO WS-R08-G02
           END-EVALUATE
           IF WS-FLAG = 'Y'
               GO TO P0353
           END-IF.
       P0357.
           MOVE 'P' TO WS-R09-F027
           MOVE WS-REC-09 TO WS-REC-08
           MOVE WS-R08-F030 TO WS-RDF-09-TAIL
           MOVE 'K' TO WS-R09-F019
           EVALUATE WS-MODE
             WHEN 'A1'
               MOVE ZERO TO WS-R08-F023
               MOVE 'R' TO WS-R08-F026
             WHEN 'B2'
               MOVE WS-REC-09 TO WS-REC-08
               MOVE WS-TAB-08-TXT(WS-IX-2) TO WS-R08-F029
             WHEN 'C3'
               MOVE SPACES TO WS-R09-G05
               MOVE WS-R09-F020 TO WS-RDF-06-HEAD
             WHEN OTHER
               MOVE SPACES TO WS-R08-G02
               MOVE WS-REC-09 TO WS-REC-08
               MOVE ZERO TO WS-R08-F031
           END-EVALUATE.
       P0358.
           MOVE WS-REC-09 TO WS-REC-08
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           COMPUTE WS-IX-3 = WS-IX-3 + 1
           MOVE ZERO TO WS-R08-F035
           IF WS-R08-F035 = ZERO
               MOVE 'C' TO WS-R08-F032
               MOVE WS-TAB-06-TXT(WS-IX-7) TO WS-R09-F021
               MOVE WS-REC-08 TO WS-REC-09
           ELSE
               MOVE WS-REC-08 TO WS-REC-09
               MOVE ZERO TO WS-R08-F031
           END-IF.
       P0359.
           MOVE 'Z' TO WS-R09-F027(1:1)
           MOVE 'Z' TO WS-R09-F023(4:1)
           IF WS-R08-F000 = SPACES
               MOVE WS-REC-09 TO WS-REC-08
               MOVE SPACES TO WS-R08-G02
           ELSE
               MOVE SPACES TO WS-R08-G00
               MOVE WS-R08-F006 TO WS-TAB-00-KEY(WS-IX-7)
               MOVE ZERO TO WS-R09-F021
           END-IF.
       P0360.
           MOVE WS-TAB-11-TXT(WS-IX-4) TO WS-R09-F010
           MOVE 'Z' TO WS-R09-F030(8:1)
           MOVE 'X' TO WS-R09-F027
           CONTINUE.
