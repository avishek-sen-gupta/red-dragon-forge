"""A member's source as the Db2 precompiler leaves it for the compiler: EXEC SQL INCLUDE expanded as COPY."""

from cobol_asg.source_text import decode_source
from squall.preprocess import apply_sql_prepass


def precompiled(source: bytes) -> bytes:
    return apply_sql_prepass(decode_source(source)).encode("latin-1")
