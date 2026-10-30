DDCOPY   CSECT
         BASR  12,0
         USING *,12
         LR    11,14
         OPEN  (INDCB,(INPUT))
         LTR   15,15
         BNZ   DONE
         MVC   OUTDCB+RECFM(1),INDCB+RECFM
         MVC   OUTDCB+LRECL(2),INDCB+LRECL
         OPEN  (OUTDCB,(OUTPUT))
         LTR   15,15
         BNZ   DONE
LOOP     GET   INDCB,REC
         PUT   OUTDCB,REC
         B     LOOP
EOF      CLOSE (INDCB,,OUTDCB)
         SR    15,15
DONE     LR    14,11
         BR    14
         LTORG
RECFM    EQU   36
LRECL    EQU   82
REC      DS    CL104
INDCB    DCB   DSORG=PS,MACRF=GM,                                      X
               DDNAME=INDD,EODAD=EOF
OUTDCB   DCB   DSORG=PS,MACRF=PM,DDNAME=OUTDD
         END
