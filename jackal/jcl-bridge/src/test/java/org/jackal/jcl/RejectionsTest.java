package org.jackal.jcl;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

/** Malformed JCL the grammar accepts, each rejected by the serializer with a named reason. */
public class RejectionsTest {

    private static String rejection(String... lines) {
        return assertThrows(JclSerializer.SyntaxErrorException.class,
                () -> JclSerializer.serialize(String.join("\n", lines) + "\n")).getMessage();
    }

    @Test
    public void eachMalformedConstructIsRejectedWithItsReason() {
        assertEquals("ELSE twice in one IF", rejection(
                "//J JOB (A),CLASS=A",
                "//T IF ABEND THEN",
                "//S1 EXEC PGM=A",
                "// ELSE",
                "//S2 EXEC PGM=B",
                "// ELSE",
                "//S3 EXEC PGM=C",
                "// ENDIF"));
        assertEquals("COND names more than one of EVEN and ONLY", rejection(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC PGM=A,COND=((4,LT),ONLY,EVEN)"));
        assertEquals("COND return code is not a number: X", rejection(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC PGM=A,COND=(X,LT)"));
        assertEquals("COND operator is not GT, GE, EQ, NE, LT or LE: XX", rejection(
                "//J JOB (A),CLASS=A",
                "//S1 EXEC PGM=A,COND=(4,XX)"));
    }
}
