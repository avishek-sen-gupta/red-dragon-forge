//ACCEPT   JOB (A),'ACCEPT',CLASS=A
//S1       EXEC PGM=PGMA
//T1       IF RC NG 4 THEN
//S2       EXEC PGM=PGMB
//         ENDIF
//T2       IF ABEND THEN
//S3       EXEC PGM=PGMC
//         ENDIF
//T3       IF S1.ABEND THEN
//S4       EXEC PGM=PGMD
//         ENDIF
//T4       IF ¬ABEND THEN
//S5       EXEC PGM=PGME
//         ENDIF
//T5       IF ABENDCC = U0100 THEN
//S6       EXEC PGM=PGMF
//         ENDIF
//T6       IF S1.ABENDCC = S0C7 THEN
//S7       EXEC PGM=PGMG
//         ENDIF
//T7       IF S1.RUN AND (S1.RC < 8 OR NOT S1.ABEND) THEN
//S8       EXEC PGM=PGMH
//         ENDIF
//T8       IF S1.RUN & (S1.RC NL 2 | ¬S1.RUN) THEN
//S9       EXEC PGM=PGMI
//         ENDIF
