"""SQL-owned COBOL statement types, ported from Squall.

Squall is a peer of Cicada, not a dependent of it: EXEC SQL is a coprocessor
extension, neither part of the COBOL language nor a CICS facility. This package
holds the one piece of Squall the knowledge-graph cobble needs — the parse-time
``DialectParser`` that turns the bridge's ``EXEC_SQL`` JSON into a typed
statement. None of Squall's runtime (backends, binding engine, lowering
strategy, the SQL grammar) is ported: the graph does not execute SQL.
"""
