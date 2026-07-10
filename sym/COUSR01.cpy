       01  COUSR1AO.
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
           02  FNAMEL                          PIC S9(4) COMP.
           02  FNAMEA                          PIC X.
           02  FILLER REDEFINES FNAMEA.
               03  FNAMEF                      PIC X.
           02  FNAMEC                          PIC X.
           02  FNAMEP                          PIC X.
           02  FNAMEH                          PIC X.
           02  FNAMEV                          PIC X.
           02  FNAMEO                          PIC X(20).
           02  LNAMEL                          PIC S9(4) COMP.
           02  LNAMEA                          PIC X.
           02  FILLER REDEFINES LNAMEA.
               03  LNAMEF                      PIC X.
           02  LNAMEC                          PIC X.
           02  LNAMEP                          PIC X.
           02  LNAMEH                          PIC X.
           02  LNAMEV                          PIC X.
           02  LNAMEO                          PIC X(20).
           02  USERIDL                         PIC S9(4) COMP.
           02  USERIDA                         PIC X.
           02  FILLER REDEFINES USERIDA.
               03  USERIDF                     PIC X.
           02  USERIDC                         PIC X.
           02  USERIDP                         PIC X.
           02  USERIDH                         PIC X.
           02  USERIDV                         PIC X.
           02  USERIDO                         PIC X(8).
           02  PASSWDL                         PIC S9(4) COMP.
           02  PASSWDA                         PIC X.
           02  FILLER REDEFINES PASSWDA.
               03  PASSWDF                     PIC X.
           02  PASSWDC                         PIC X.
           02  PASSWDP                         PIC X.
           02  PASSWDH                         PIC X.
           02  PASSWDV                         PIC X.
           02  PASSWDO                         PIC X(8).
           02  USRTYPEL                        PIC S9(4) COMP.
           02  USRTYPEA                        PIC X.
           02  FILLER REDEFINES USRTYPEA.
               03  USRTYPEF                    PIC X.
           02  USRTYPEC                        PIC X.
           02  USRTYPEP                        PIC X.
           02  USRTYPEH                        PIC X.
           02  USRTYPEV                        PIC X.
           02  USRTYPEO                        PIC X(1).
           02  ERRMSGL                         PIC S9(4) COMP.
           02  ERRMSGA                         PIC X.
           02  FILLER REDEFINES ERRMSGA.
               03  ERRMSGF                     PIC X.
           02  ERRMSGC                         PIC X.
           02  ERRMSGP                         PIC X.
           02  ERRMSGH                         PIC X.
           02  ERRMSGV                         PIC X.
           02  ERRMSGO                         PIC X(78).
       01  COUSR1AI REDEFINES COUSR1AO.
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
           02  FNAMEI                          PIC X(20).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  LNAMEI                          PIC X(20).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  USERIDI                         PIC X(8).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  PASSWDI                         PIC X(8).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  USRTYPEI                        PIC X(1).
           02  FILLER                          PIC S9(4) COMP.
           02  FILLER                          PIC X.
           02  FILLER                          PIC X(4).
           02  ERRMSGI                         PIC X(78).
