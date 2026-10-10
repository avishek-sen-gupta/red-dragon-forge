//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//         SET HLQ=T1,X=A,X=B
//S1       EXEC PGM=PGMA,PARM='&X'
//IN       DD DSN=&HLQ..IN,DISP=SHR
//         SET HLQ=T2,SFX=
//         SET LIB=&HLQ..LIB
//S2       EXEC PGM=PGMB,PARM='A&SFX'
//IN       DD DSN=&LIB,DISP=SHR
//S3       EXEC SETP,MODE=EXEC
//C1       IF (S1.RC = 0) THEN
//S4       EXEC PGM=PGMC
//         ELSE
//         SET HLQ=T4
//         ENDIF
//S5       EXEC PGM=PGMD
//IN       DD DSN=&HLQ..IN,DISP=SHR
