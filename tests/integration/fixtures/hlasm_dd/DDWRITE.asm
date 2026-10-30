DDWRITE  CSECT
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
REC1     DC    CL80'FIRST RECORD'
REC2     DC    CL80'SECOND RECORD'
REC3     DC    CL80'THIRD RECORD'
OUTDCB   DCB   DSORG=PS,MACRF=PM,DDNAME=OUTDD
         END
