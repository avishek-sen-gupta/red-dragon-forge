//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//C1       IF (S1.RC = 0) THEN
//S2       EXEC PGM=PGMB
//C2       IF (S2.RC > 4) THEN
//S3       EXEC PGM=PGMC
//         ENDIF
//         ELSE
//S4       EXEC PGM=PGMD
//         ENDIF
//S5       EXEC PGM=PGME
