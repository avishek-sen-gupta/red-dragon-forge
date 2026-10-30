DDWRITEV CSECT
         BASR  12,0
         USING *,12
         LR    11,14
         OPEN  (OUTDCB,(OUTPUT))
         LTR   15,15
         BNZ   DONE
         PUT   OUTDCB,REC1
         PUT   OUTDCB,REC2
         PUT   OUTDCB,REC3
         CLOSE (OUTDCB)
         SR    15,15
DONE     LR    14,11
         BR    14
         LTORG
REC1     DC    H'6',H'0',C'AB'
REC2     DC    H'16',H'0',C'HELLO, WORLD'
REC3     DC    H'104',H'0',100C'Z'
OUTDCB   DCB   DSORG=PS,MACRF=PM,DDNAME=OUTDD
         END
