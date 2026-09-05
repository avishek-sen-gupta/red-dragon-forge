"""depgraph — the coarse variable dependency graph, built from the raw AST.

The input is the ASG cache cobble.parsing wrote; nothing here parses COBOL.

Modules, in the order a corpus goes through them:

    cics_cache    EXEC CICS read back out of that cache, which cicada's own
                  dialect parser cannot do (it wants the bridge's raw text)
    flows         the verb table: one statement -> the names it reads and writes
    graph         the two passes: literal edges, then the collapse
    checker       fan-in/fan-out/adjacency per name, for judging conduits
    build         the driver: walks the cache, runs both passes, emits the graph
    render        the graph as one self-contained WebGL page

Coarse means no byte-level fidelity: a node is a NAME, an edge is "this name's
value reached that one", and REDEFINES is handled by aliasing names whose byte
ranges coincide. Field-level precision is dataflow/layout.py's business and is
deliberately not attempted here.
"""
