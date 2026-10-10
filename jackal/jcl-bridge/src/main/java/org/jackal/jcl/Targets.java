package org.jackal.jcl;

import com.google.gson.JsonObject;

/** The step a COND test, an IF term or a referback points at. */
final class Targets {

    private Targets() {
    }

    static JsonObject allPrior() {
        JsonObject target = new JsonObject();
        target.addProperty("kind", "all_prior");
        return target;
    }

    static JsonObject named(String dotted) {
        String[] names = dotted.split("\\.");
        JsonObject target = new JsonObject();
        if (names.length == 1) {
            target.addProperty("kind", "step");
            target.addProperty("step", names[0]);
            return target;
        }
        if (names.length != 2) {
            throw new JclSerializer.SyntaxErrorException("step reference with more than two names: " + dotted);
        }
        target.addProperty("kind", "proc_step");
        target.addProperty("call", names[0]);
        target.addProperty("step", names[1]);
        return target;
    }
}
