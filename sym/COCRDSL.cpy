       01  CCRDSLAO.
           02  FILLER                          PIC X(12).
           02  TRNNAMEL                        PIC S9(4) COMP.
           02  TRNNAMEA                        PIC X.
           02  FILLER REDEFINES TRNNAMEA.
               03  TRNNAMEF                    PIC X.
           02  TRNNAMEC                        PIC X.
           02  TRNNAMEP                        PIC X.
           02  TRNNAMEH                        PIC X.
           02  TRNNAMEV                        PIC X.
           02  TRNNAMEO                        PIC X(4).
           02  TITLE01L                        PIC S9(4) COMP.
           02  TITLE01A                        PIC X.
           02  FILLER REDEFINES TITLE01A.
               03  TITLE01F                    PIC X.
           02  TITLE01C                        PIC X.
           02  TITLE01P                        PIC X.
           02  TITLE01H                        PIC X.
           02  TITLE01V                        PIC X.
           02  TITLE01O                        PIC X(40).
           02  CURDATEL                        PIC S9(4) COMP.
           02  CURDATEA                        PIC X.
           02  FILLER REDEFINES CURDATEA.
               03  CURDATEF                    PIC X.
           02  CURDATEC                        PIC X.
           02  CURDATEP                        PIC X.
           02  CURDATEH                        PIC X.
           02  CURDATEV                        PIC X.
           02  CURDATEO                        PIC X(8).
           02  PGMNAMEL                        PIC S9(4) COMP.
           02  PGMNAMEA                        PIC X.
           02  FILLER REDEFINES PGMNAMEA.
               03  PGMNAMEF                    PIC X.
           02  PGMNAMEC                        PIC X.
           02  PGMNAMEP                        PIC X.
           02  PGMNAMEH                        PIC X.
           02  PGMNAMEV                        PIC X.
           02  PGMNAMEO                        PIC X(8).
           02  TITLE02L                        PIC S9(4) COMP.
           02  TITLE02A                        PIC X.
           02  FILLER REDEFINES TITLE02A.
               03  TITLE02F                    PIC X.
           02  TITLE02C                        PIC X.
           02  TITLE02P                        PIC X.
           02  TITLE02H                        PIC X.
           02  TITLE02V                        PIC X.
           02  TITLE02O                        PIC X(40).
           02  CURTIMEL                        PIC S9(4) COMP.
           02  CURTIMEA                        PIC X.
           02  FILLER REDEFINES CURTIMEA.
               03  CURTIMEF                    PIC X.
           02  CURTIMEC                        PIC X.
           02  CURTIMEP                        PIC X.
           02  CURTIMEH                        PIC X.
           02  CURTIMEV                        PIC X.
           02  CURTIMEO                        PIC X(8).
           02  ACCTSIDL                        PIC S9(4) COMP.
           02  ACCTSIDA                        PIC X.
           02  FILLER REDEFINES ACCTSIDA.
               03  ACCTSIDF                    PIC X.
           02  ACCTSIDC                        PIC X.
           02  ACCTSIDP                        PIC X.
           02  ACCTSIDH                        PIC X.
           02  ACCTSIDV                        PIC X.
           02  ACCTSIDO                        PIC X(11).
           02  CARDSIDL                        PIC S9(4) COMP.
           02  CARDSIDA                        PIC X.
           02  FILLER REDEFINES CARDSIDA.
               03  CARDSIDF                    PIC X.
           02  CARDSIDC                        PIC X.
           02  CARDSIDP                        PIC X.
           02  CARDSIDH                        PIC X.
           02  CARDSIDV                        PIC X.
           02  CARDSIDO                        PIC X(16).
           02  CRDNAMEL                        PIC S9(4) COMP.
           02  CRDNAMEA                        PIC X.
           02  FILLER REDEFINES CRDNAMEA.
               03  CRDNAMEF                    PIC X.
           02  CRDNAMEC                        PIC X.
           02  CRDNAMEP                        PIC X.
           02  CRDNAMEH                        PIC X.
           02  CRDNAMEV                        PIC X.
           02  CRDNAMEO                        PIC X(50).
           02  CRDSTCDL                        PIC S9(4) COMP.
           02  CRDSTCDA                        PIC X.
           02  FILLER REDEFINES CRDSTCDA.
               03  CRDSTCDF                    PIC X.
           02  CRDSTCDC                        PIC X.
           02  CRDSTCDP                        PIC X.
           02  CRDSTCDH                        PIC X.
           02  CRDSTCDV                        PIC X.
           02  CRDSTCDO                        PIC X(1).
           02  EXPMONL                         PIC S9(4) COMP.
           02  EXPMONA                         PIC X.
           02  FILLER REDEFINES EXPMONA.
               03  EXPMONF                     PIC X.
           02  EXPMONC                         PIC X.
           02  EXPMONP                         PIC X.
           02  EXPMONH                         PIC X.
           02  EXPMONV                         PIC X.
           02  EXPMONO                         PIC X(2).
           02  EXPYEARL                        PIC S9(4) COMP.
           02  EXPYEARA                        PIC X.
           02  FILLER REDEFINES EXPYEARA.
               03  EXPYEARF                    PIC X.
           02  EXPYEARC                        PIC X.
           02  EXPYEARP                        PIC X.
           02  EXPYEARH                        PIC X.
           02  EXPYEARV                        PIC X.
           02  EXPYEARO                        PIC X(4).
           02  INFOMSGL                        PIC S9(4) COMP.
           02  INFOMSGA                        PIC X.
           02  FILLER REDEFINES INFOMSGA.
               03  INFOMSGF                    PIC X.
           02  INFOMSGC                        PIC X.
           02  INFOMSGP                        PIC X.
           02  INFOMSGH                        PIC X.
           02  INFOMSGV                        PIC X.
           02  INFOMSGO                        PIC X(40).
           02  ERRMSGL                         PIC S9(4) COMP.
           02  ERRMSGA                         PIC X.
           02  FILLER REDEFINES ERRMSGA.
               03  ERRMSGF                     PIC X.
           02  ERRMSGC                         PIC X.
           02  ERRMSGP                         PIC X.
           02  ERRMSGH                         PIC X.
           02  ERRMSGV                         PIC X.
           02  ERRMSGO                         PIC X(80).
           02  FKEYSL                          PIC S9(4) COMP.
           02  FKEYSA                          PIC X.
           02  FILLER REDEFINES FKEYSA.
               03  FKEYSF                      PIC X.
           02  FKEYSC                          PIC X.
           02  FKEYSP                          PIC X.
           02  FKEYSH                          PIC X.
           02  FKEYSV                          PIC X.
           02  FKEYSO                          PIC X(75).
       01  CCRDSLAI REDEFINES CCRDSLAO.
           02  FILLER                          PIC X(12).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  TRNNAMEI                        PIC X(4).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  TITLE01I                        PIC X(40).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  CURDATEI                        PIC X(8).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  PGMNAMEI                        PIC X(8).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  TITLE02I                        PIC X(40).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  CURTIMEI                        PIC X(8).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  ACCTSIDI                        PIC X(11).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  CARDSIDI                        PIC X(16).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  CRDNAMEI                        PIC X(50).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  CRDSTCDI                        PIC X(1).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  EXPMONI                         PIC X(2).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  EXPYEARI                        PIC X(4).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  INFOMSGI                        PIC X(40).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  ERRMSGI                         PIC X(80).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  FKEYSI                          PIC X(75).
