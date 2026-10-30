"""A member with an EXEC SQL INCLUDE in its procedure division, as written and as the Db2 precompiler leaves it."""

WRITTEN = (
    "       PROCEDURE DIVISION.\n"
    "           EXEC SQL INCLUDE CSDB2RPY END-EXEC\n"
    "           DISPLAY '\xa3'.\n"
).encode("latin-1")

PRECOMPILED = (
    "       PROCEDURE DIVISION.\n"
    "           COPY CSDB2RPY.\n"
    "           DISPLAY '\xa3'.\n"
)
