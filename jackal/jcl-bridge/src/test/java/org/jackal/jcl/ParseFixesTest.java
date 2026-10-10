package org.jackal.jcl;

import com.google.gson.JsonObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

/** Constructs the grammar rejected, each of which lost the whole job. */
public class ParseFixesTest {

    private static JsonObject job(String... lines) {
        return JclSerializer.serialize(String.join("\n", lines) + "\n");
    }

    private static int steps(JsonObject job) {
        return job.getAsJsonArray("statements").size();
    }

    @Test
    public void aDcbModelNameStartingWithAKeywordParses() {
        assertEquals(2, steps(job(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC PGM=X",
                "//A DD DSN=T.A,DCB=T.MODEL",
                "//B DD DSN=T.B,DCB=(CODES.X,RECFM=FB,LRECL=80)",
                "//C DD DSN=T.C,DCB=(DENX.Y)",
                "//S2 EXEC PGM=Y")));
    }

    @Test
    public void aJobCondWithTwoTestsParses() {
        assertEquals(2, job(
                "//J JOB (A),CLASS=A,COND=((8,LE),(12,EQ))",
                "//S1 EXEC PGM=X").getAsJsonArray("end_job_tests").size());
    }

    @Test
    public void anEmptyParmOrCondOverrideParses() {
        assertEquals(4, steps(job(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC P,PARM.P1=''",
                "//S2 EXEC P,PARM.P1=,COND.P2=(4,LT)",
                "//S3 EXEC P,PARM=''",
                "//S4 EXEC P,COND=")));
    }

    @Test
    public void aDdParameterWithNoValueParses() {
        JsonObject job = job(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC P",
                "//P1.IN DD DSN=T.X,UNIT=,VOL=,SPACE=,DCB=,EXPDT=",
                "//P1.OUT DD DISP=,DSN=",
                "//S2 EXEC PGM=Y");
        assertEquals(2, steps(job));
        assertEquals(
                "[{\"procstep\":\"P1\",\"dd\":{\"ddname\":\"IN\",\"dsn\":{\"kind\":\"name\","
                        + "\"value\":[{\"kind\":\"literal\",\"text\":\"T.X\"}]},\"disp\":[],\"nullified\":[],"
                        + "\"in_stream\":[],\"sysout\":false,\"concatenated\":[]}},"
                        + "{\"procstep\":\"P1\",\"dd\":{\"ddname\":\"OUT\",\"dsn\":{\"kind\":\"none\"},"
                        + "\"disp\":[],\"nullified\":[\"disp\",\"dsn\"],\"in_stream\":[],\"sysout\":false,"
                        + "\"concatenated\":[]}}]",
                job.getAsJsonArray("statements").get(0).getAsJsonObject()
                        .getAsJsonArray("dd_overrides").toString());
    }

    @Test
    public void theWordNotInAnIfParses() {
        assertEquals(2, steps(job(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC PGM=X",
                "//T1 IF NOT S1.ABEND THEN",
                "//S2 EXEC PGM=Y",
                "// ENDIF")));
    }

    @Test
    public void aQuotedOnlyPositionalFollowedByAContinuationParses() {
        assertEquals("J1", job(
                "//J1 JOB 'EXTRACT TRAN',",
                "//  CLASS=A",
                "//S1 EXEC PGM=X").get("name").getAsString());
    }
}
