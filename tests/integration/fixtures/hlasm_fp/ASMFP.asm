ASMFP    CSECT
         BALR  12,0
         USING *,12
         L     2,0(,1)
         LD    1,B100
         LD    2,B275
         ADBR  1,2
         CFDBR 3,5,1
         ST    3,0(,2)
         LD    1,H100
         LD    2,H275
         ADR   1,2
         CFDR  3,5,1
         ST    3,4(,2)
         LD    1,D100
         LD    2,D275
         ADTR  3,1,2
         CGDTR 3,0,3
         ST    3,8(,2)
         SR    15,15
         BR    14
         DS    0D
B100     DC    X'4059000000000000'
B275     DC    X'4071300000000000'
H100     DC    X'4264000000000000'
H275     DC    X'4311300000000000'
D100     DC    X'2238000000000080'
D275     DC    X'2238000000000175'
         END
